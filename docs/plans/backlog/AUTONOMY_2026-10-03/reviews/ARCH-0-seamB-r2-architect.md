**Verdict: REQUEST_CHANGES.** E-7d: **AMEND** (small). E-7e: **AMEND** (blocking). I can't adopt E-7e as written.

The r2 plan closes all 17 r1 architect findings and follows B-R1..B-R8. The gate design has been measured and holds up. The problem is the new mount set in E-7e(c): it breaks several consumer plans that E-7e(f) never lists. The worst case is that every bus-reading row in AUT-1 and AUT-6 loses `systemctl --user`. There is also one argv shape nobody has measured (`--unshare-user` plus `--proc` without `--unshare-pid`).

| Axis | Score |
|---|---|
| Correctness | 6 |
| Architecture fit | 8 |
| Test coverage | 7 |
| Risk mitigation | 7 |
| Scope minimality | 7 |
| Feasibility | 6 |

## 1. Fidelity to B-R1..B-R8 (checked against the r2 text, not the disposition table)

- **B-R1: met, with one justified deviation.** The ruling said "collect `-m bwrap_host tests/`". r2 runs an exact file registry instead. The reason is sound: `tests/unit/conftest.py:20-21` imports `breezy.strategy`, which pulls in Nautilus (M2), so collecting all of `tests/` would trip the blocker. The other parts are present: the blocker refuses egress hits, the N2 widening is exact-set with a byte-identical absent path, the session-end check exists, and children get `--unshare-net`. Security sign-off is still owed.
- **B-R2: met.** Amendments (a), (b) and (c) are all present.
- **B-R3: met.**
- **B-R4: met,** except for the live-listing problem in finding 6.
- **B-R5: met.**
- **B-R6: exceeded, but it creates a regression** (finding 1). Hiding all of home is better than the ruled name list (L-14, M12, M7). The ruled `--tmpfs /run/user/<uid>` was never checked against consumer bus clients.
- **B-R7: met.** I checked r1 architect findings 1–17 one by one against the r2 text; each is fixed where the table says.
- **B-R8: met.**

## 2. ER verdicts

- **E-7d: AMEND.** Add four things:
  - the script dispatch fix and the unshare-host behaviour (finding 4);
  - a self-contained witness so B2a is green at its own sha (finding 8);
  - a "Supersedes" line that names B-R1's `-m bwrap_host tests/` wording as well as AUT-5 l.287;
  - a fixed or cleaned phase-2 basetemp (finding 11).
- **E-7e: AMEND.**
  - (c) needs a named user-bus exception (finding 1) and a measured `/proc` shape for `E7A_R2_PROC` rows (finding 2).
  - (f) must list the consumer breaks in findings 1, 3, 5, 7 and 9.
  - (a), (b), (d), (e) and (g) can be adopted as written, except that (d) needs finding 6.

## 3. Findings

**1. HIGH — §AC-1.3 step 5 / E-7e(c): `--tmpfs /run/user/<uid>` breaks every wrapped user-bus client, and E-7e(f) doesn't list it.**
- **Problem:** Several consumer rows run `systemctl --user` inside the wrapper:
  - AUT-6 r15 runs `systemctl --user show/list-units/list-timers` in the `producer-daily`, `health` and `breezy-autonomy-failed@` rows (l.203-207, l.802, l.948, l.966).
  - AUT-1 r12 capture-audit runs the read-only `systemctl --user show` argv (l.939). The stall-drill and drill-guard rows say "plus the user-bus socket if V-9 requires it" (l.883-884, l.1343).
  
  With `/run/user/1000` an empty tmpfs (M9), every one of these calls fails to connect to the bus. AUT-6 health then reads UNKNOWN on every pass, and #29/dead-man fire within about 30 minutes, every day. The notifier also cannot prove a pending restart.
  
  The plan has no mechanism to fix this, because binds are data-root-relative only, so AUT-1's "bus socket bind" cannot even be expressed.
- **Fix:**
  - Add a named exception `E7A_R2_USER_BUS` to `KNOWN_EXCEPTIONS` and E-7e(e). It is an exact row set: AUT-6 daily, health and failed@; AUT-1 capture-audit, drill and drill-guard.
  - For those rows, ro-re-bind only `/run/user/<uid>/systemd/private` after the tmpfs (connect through an ro bind works, M10).
  - State the residual: these rows can drive the user manager, including transient units that escape the sandbox. The second layer is each consumer's AC6 allowlist, restricted to literal `systemctl --user show|list-units|list-timers` and `journalctl` argvs, and never `systemd-run`.
  - Add a phase-2 test, `test_bwrap_user_bus_row_systemctl_show_succeeds_and_others_enoent`, and a V-step equivalent to V14.
  - Security must rule on this. Add it to E-7e(f) for AUT-1 and AUT-6.

**2. HIGH — §AC-1.3 steps 1/2/9 / M5: `--unshare-user` plus `--proc /proc` without `--unshare-pid` has not been shown to work.**
- **Problem:** Mounting procfs needs CAP_SYS_ADMIN in the user namespace that owns the pid namespace. A new user namespace that stays in the host pid namespace normally gets EPERM ("Can't mount proc on /newroot/proc"). M5's "152 lines without `--unshare-pid`" doesn't say whether `--unshare-user` was also set. If it fails, every `E7A_R2_PROC` row exits 1 at mount, which takes down AUT-6 health, AUT-6 intraday #evaluate and every `/proc/locks` consumer. This is the L-47 failure mode: one unverified premise.
- **Fix:**
  - Add a verify-first measurement (M14) of the exact `E7A_R2_PROC` argv.
  - If it fails, omit `--proc /proc` for those rows; the recursive `--ro-bind / /` already exposes the host `/proc`. Pin that with `test_argv_proc_rows_omit_proc_mount`.
  - Add a phase-2 test `test_bwrap_proc_row_reads_host_proc_locks_and_pid_status`.

**3. HIGH — E-7e(f), AUT-6: two unlisted test breaks.**
- **Problem:**
  - AUT-6 r15 l.1333-1349 puts its real-bwrap tests in `tests/unit/test_integrity_floor_bwrap.py`. Under E-7d these cannot run in phase 1, because nested bwrap is denied. They also cannot join the registry, because E-7d's consumer obligation puts phase-2 files outside `tests/unit/`, whose conftest loads Nautilus. Those tests are:
    - `test_bwrap_self_probe_negative_state_write_fails_erofs`
    - the positive-control test
    - `test_bwrap_self_probe_failure_exits_integrity_with_delivered_critical_and_no_demand_file`
    - `test_demand_stage_hard_killed_at_budget`
  - l.1334 also asserts `--tmpfs ~/.config` in the rendered argv, which E-7e(c) removes.
- **Fix:** E-7e(f) AUT-6 must say three things:
  - the real-bwrap tests move to `tests/integration/` and join `BWRAP_HOST_TEST_FILES`, while the parse-only tests stay in unit;
  - the l.1334 and l.243 `--tmpfs ~/.config` assertions become home-allowlist assertions;
  - the user-bus row from finding 1.

**4. MEDIUM — §Gate / Script: dropping `exec` makes the dispatch fall through.**
- **Problem:** `run_tests_no_egress.sh:54-70` is two independent `if` blocks followed by an unconditional `exit 3`. Without `exec`, a successful bwrap phase 1 falls into the unshare block. On a host where both mechanisms work, phase 1 runs twice. Then the script reaches the refusal and `exit 3` before phase 2. r2 only says "`run_bwrap "$@" || phase1_rc=$?`".
  
  Separately, on unshare-only hosts phase 2 now always refuses with 3. That changes how the gate behaves on those hosts, and the change isn't stated anywhere.
- **Fix:**
  - Specify `if bwrap-ok … elif unshare-ok … else refuse-3; fi` around phase 1.
  - Add `test_phase1_runs_exactly_once_when_bwrap_and_unshare_both_usable` (both stubs on `PATH`, invocation counter).
  - State the unshare-only behaviour in E-7d Rule 1.

**5. MEDIUM — §AC-5 / Edge row "ExecStopPost hook": the AUT-1 recorder can never pass the lint.**
- **Problem:** "Every unit naming the wrapper is in scope", and the rule is "every `ExecStart=`/`ExecStopPost=` goes timeout → wrapper". `breezy-quote-tape.service` names the wrapper only in its stop hook. Its `ExecStart` is unwrapped python by design (E-7a rule 5; AUT-1 l.896). Its `ExecStartPre` lines aren't bounded `install -d` either. AC-5 fails on that file permanently.
- **Fix:** For a unit that is in scope only because it names the wrapper (it is not in `AUTONOMY_OWNED_UNITS` and not a row unit), lint only the lines that name the wrapper. Each of those must be timeout → wrapper → a row whose `units` lists that unit. Add a positive-control fixture of a recorder-shaped unit.

**6. MEDIUM — §AC-2 step 3: the live-listing negatives make the probe set non-deterministic.**
- **Problem:** "every top-level data-root directory not covered by a bind (live listing)" makes `self_probe_plan` depend on the host. AUT-6 r15 l.262 pins `AUT6_SELF_PROBE_PATHS: Final` equal to the table derivation, so that test becomes host-dependent. It also adds nothing: every unbound data-root directory sits on the same ro rebind as the data root, which is already a negative.
- **Fix:**
  - Drop the live-listing clause (YAGNI). Keep `state/`, `registry/`, the data root, the repo and the unbound ancestors.
  - Also keep AUT-6's "directory owned by this uid" stat precondition (l.260), which AC-2 currently omits.

**7. MEDIUM — E-7e(f), AUT-5: incomplete.**
- **Problem:** The list is missing three things:
  - The per-mode drop-ins (l.281 bootstrap `derived/artefacts`; l.282 stage-S `registry-shadow`, which also applies to the dead-man) need distinct rows. The stage-S rows share a unit name with the normal rows, so they need `#stage-s` rows, and the units should use exact instance names, not `name@`, so a daily unit can't select the bootstrap row.
  - l.284 `test_engine_unit_sandbox_config_covers_every_writer` parses the inline argv and asserts `--tmpfs %h/.config`; it must derive from the table instead.
  - l.286's "probe file unlinked" wording.
- **Fix:** Add these to E-7e(f).

**8. MEDIUM — §Work Packages, B2a/B2b: B2a can't be green at its own sha.**
- **Problem:** B2a's registry names B2b's files, and B2a's own `test_p2_child_admitted_collects_registry…` needs a witness file to exist. "Merged together" defeats L-54's intent that the firewall edit be a separately gated item, and L-43's per-merge gate.
- **Fix:**
  - B2a ships `tests/integration/test_bwrap_host_phase_witness.py`, which asserts the blocker is at `meta_path[0]`, no refused module is loaded, and a harness-free `bwrap … true` child exits 0. It also sets `BWRAP_HOST_EXPECTED_TESTS` to that count.
  - B2b then only widens the registry and the count. Each WP gets a full two-phase gate.
  - State that E-7d must be filed before B2a merges.

**9. LOW-MED — E-7e(f): other unlisted consumer edits.**
- AUT-1 l.906 plans to re-bind `alerts.env` from `~/.config/breezy`, which `validate_table` refuses. It's unnecessary anyway, because `EnvironmentFile` is read by systemd. AUT-1 l.905 `OnFailure=breezy-study-failed@` also needs the same switch as AUT-5 (R10).
- AUT-3 r6 l.296 extracts into `~/.cache/breezy/refit-repro/`. That path is outside the data root, so it can't be a bind, and it is hidden. It must move to `cache/refit-repro/` under the data root.
- AUT-4 l.881 inspects "the wrapper source" for `--size`/`--tmpfs`, but that logic is now in `bwrap.py`. Also, all AUT-4 real-bwrap tests join the registry, not just the fixture row: `test_each_aut4_row_has_private_tmp`, `test_tmpfs_cap_enforced_enospc` and `test_aut4_wal_reads.py`.

**10. LOW — §AC-1.3: library cache writes under a read-only home.**
- Hiding home makes `~/.cache` read-only. XDG-honouring libraries in AUT-3/AUT-4 rows then fail at runtime instead of at V-steps.
- **Fix:** add `--setenv XDG_CACHE_HOME /tmp/.cache` (E-7c scratch) and note it under R17.

**11. LOW — §Script `run_phase2`: basetemp litter.**
- `phase2-bt-$$` is never removed, so one directory accumulates per run and per T1 lane.
- **Fix:** use `phase2-bt` (pytest clears it per run; lanes need `phase2-bt-lane$i`), or `rm -rf` it on exit.

**12. LOW — Hygiene.**
- Line 1 of the plan is agent chatter ("Evidence is complete…"); strip it.
- The `…/autonomy_sandbox/…` and `…/breezy-autonomy-bwrap` ellipses in the file plan, V2 and V12 must be literal absolute paths in briefs.

## 4. Gate design (Q4)

The design is sound and is the simplest one that meets B-R1:
- **One script, two phases:** correct, once finding 4 is fixed.
- **Exact registry instead of `-m bwrap_host tests/`:** required by M2. It is AST-equality-pinned, and `test_p2_child_admitted_collects_registry` will catch a future Nautilus-importing ancestor conftest (for example under `tests/integration/autonomy/`).
- **`BWRAP_HOST_EXPECTED_TESTS`:** partly redundant with "0 skipped, unmarked item exits 2, registry equality". Its remaining value is catching a deleted test inside a registry file. Keep it; the cost is merge conflicts on one literal, and those conflicts are visible.
- **Phase 2 once per T1 lane:** wasteful but bounded. `run_t1_lanes.sh:75` will show the gate summary line as each lane's last line, which is acceptable. A "phase-2 delegated" flag would be a simpler equivalent, but it is an opt-out, and r2 rejects opt-outs for good reason. Accept R18.

## 5. Sequencing, YAGNI and LESSONS

- **Order:** B1 ∥ B2a → B2b → B3 is right once finding 8 is applied. B3 stays on the critical path for AUT-1a, AUT-5a and AUT-6.
- **YAGNI:** only the live-listing negatives (finding 6). Everything else traces to a ruling.
- **L-47:** findings 1 and 2. The B-R6 tmpfs and the `--unshare-user`/`/proc` premise were not checked against consumer reads or measured for the PROC row shape.
- **L-46:** finding 3. The real-namespace test locations in consumer plans were not searched; only the gate pins were.
- No violations of L-12, L-14, L-22, L-43, L-50, L-54 or L-55. I grepped the headers at `LESSONS.md` :620, :685, :1017, :1433, :1495, :1512, :1563, :1647 and :1664.

## Files cited
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r1-architect.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/AUT-6-r9-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md`
- `/home/jon/breezy/scripts/ci/run_tests_no_egress.sh`
- `/home/jon/breezy/scripts/ci/run_t1_lanes.sh`
- `/home/jon/breezy/src/breezy/runtime/submit_intent.py`
- `/home/jon/breezy/pyproject.toml`