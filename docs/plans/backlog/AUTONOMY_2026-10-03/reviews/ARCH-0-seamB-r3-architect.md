**Verdict: REQUEST_CHANGES.** Four blocking items remain, all small. The plan is converging.
**E-7d: ADOPT.** **E-7e: AMEND.** Parts (a), (b), (d), (e), (g) and (i) can be adopted as written. Parts (c), (f) and (h) need the amendments below.

| Axis | Score |
|---|---|
| Correctness | 7 |
| Architecture fit | 8 |
| Test coverage | 7 |
| Risk mitigation | 7 |
| Scope minimality | 8 |
| Feasibility | 8 |

## 1. My r2 findings, checked against the r3 text

| r2 | r3 status (verified in the text) |
|---|---|
| F1 user bus | **Closed, by a better route than I proposed.** M21, M22 and M25 refute `E7A_R2_USER_BUS`, which I had suggested. The bus handoff (AC-9, E-7e(h)) is the right answer. Its semantics have gaps (N1, N3 below). |
| F2 PROC argv | **Closed.** M14 and M26 measure it. The r3 shape (keep `--unshare-pid`, omit `--proc`) is stronger than the "omit `--proc` only" fallback I proposed, because host kill now gives ESRCH. Tests are named (plan l.470, l.475). |
| F3 AUT-6 test moves | **Closed** (l.425, l.836). |
| F4 dispatch | **Closed.** There is an elif chain (l.361-363), a run-once test, and the unshare-only behaviour is stated in E-7d R1. |
| F5 recorder lint | **Closed** (AC-5 l.178, with a fixture). |
| F6 live listing | **Closed.** The owner precondition is kept (AC-2.3). |
| F7 AUT-5 | **Closed** (l.409-414). S-1 retracts the r2 `-p` premise; I checked this against AUT-5 r7 l.273-275 and it is correct. |
| F8 B2a at its own sha | **Closed.** There is a witness file, and the count is 3. |
| F9 other edits | **Mostly closed** (AUT-1 alerts.env and OnFailure; AUT-3 repro; AUT-4 registry). **Not closed:** the same OnFailure class of break still exists in three other plans (N2). |
| F10 XDG cache, F11 basetemp, F12 hygiene | **Closed.** All paths are now literal absolute paths. |

**Fidelity to B3-R1..R10.** Every ruling is met. B3-R1 is exceeded: the whole of `/run` is a tmpfs plus an exact re-bind set, which is narrower than "`/run/systemd/resolve`". B3-R2: the option with no bus inside the sandbox was chosen for every consumer, and `--bus-action` is correctly gated on the r3 security ruling. One partial gap is the B3-R9 "complete" requirement (N2, N3).

## 2. Consumer Surface spot-check (30 cites)

I opened the cited lines and found these correct:
- **AUT-1 r12:** l.710, 733, 741, 768-770, 881, 883-884, 905-906, 939, 1045, 1343.
- **AUT-2 r7:** l.180, 467-470.
- **AUT-3 r6:** l.190, 267, 279-283, 296.
- **AUT-4 r11:** l.634-637, 661, 848, 871, 881, 888, 892, 898.
- **AUT-5 r7:** l.273-287, 292.
- **AUT-6 r15:** l.203-207, 247, 249, 260-262, 488, 957-958, 966, 1333-1357.

Supervisor cites `trade_supervisor.py:1186/1225/1593` and `trade_supervisor_core.py:37, 515-529, 1102-1103` are correct. `decide_stop_prior_action(None, holder)` does return `REFUSE_ALERT`, so the AC-3.2(ii) reasoning holds.

One cite is wrong: AUT-6 "l.247, 251". The health row is **l.250**; l.251 is `alert-redeliver`. That is N9.

## 3. E-7e(c): the PROC-shape amendment to E-7a rule 2

- **Substance: correct, and strictly safer than adopted E-7a.** M26 shows locks and status are readable, environ and root give EACCES, and kill gives ESRCH.
- **Consumers are pid-consistent.** AUT-6 #6 reads `/proc/locks` and then `/proc/<pid>/stat` (AUT-6 l.247), and health's RSS add-back uses `/proc/<pid>` (l.250). All of these are host pids taken from host-procfs sources or bus MainPIDs, so they stay consistent.
- **One hazard is unstated.** On a `host_proc` row, `/proc/<child.pid>` for a subprocess the row spawned itself names a **different host process**, because `Popen.pid` is a namespace pid. This belongs in the Trade-offs (l.687) and in E-7e(c), as a rule: "on `E7A_R2_PROC` rows, never index `/proc` by a namespace pid".
- **Drafting gap (N5).** E-7e(c) replaces "drop `--unshare-pid`" but leaves E-7a rule 2's test sentence ("…while its row has `unshare_pid=true`") pointing at a field that no longer exists.

## 4. Bus handoff: is it the simplest equivalent, and do the AUT-6 semantics survive?

- **Simplest equivalent: yes.**
  - `StandardOutput=` is unit-wide.
  - A separate reader unit would serve stale data.
  - The bus exception is refuted on evidence.
  - One native refinement is available for failed@. On systemd 259 the `OnFailure=` unit receives `$MONITOR_SERVICE_RESULT`, `$MONITOR_INVOCATION_ID` and related variables (L-1). These could replace the `Result,InvocationID` reads. SubState and NRestarts still need the snapshot. This is non-blocking.
- **"List before journal read": preserved by construction.** `ExecStartPre` strictly precedes `ExecStart`, so "any listed failure happened before the read began" still holds.
- **"UNKNOWN on a failed read": preserved per read only.** AC-9.2 records rc and timed_out per read and exits 0. If the step as a whole fails, the property is lost (N1).
- **Reads that are not covered** are listed in N3.

## 5. Findings

**N1. HIGH, blocking. §AC-9.2 / E-7e(h): when the snapshot step as a whole fails, `ExecStart` is skipped, which breaks AUT-6's UNKNOWN semantics and the failed@ page.**
- **Problem:**
  - Each read has a 10 s timeout, but the outer bound is `timeout -k 2 30`. Health issues at least 4 reads (l.419), plus watchdog-member, timer and rotate properties.
  - A hung user manager, which is exactly the D-Bus failure that AUT-6 l.957 maps to UNKNOWN, therefore gets the pre-step killed (124).
  - systemd then skips `ExecStart`:
    - for health: no pass runs, `passes_unknown_streak` is not incremented, and only #29's age path fires;
    - for `breezy-autonomy-failed@`, which deliberately has no `OnFailure=`: **the kill page is lost.** Today an unreadable state there means "page, cannot prove a pending restart".
  - Exits 73 and 78 have the same effect. The notifier fallback (E-7a rule 1) does not cover a failure that happens before the wrapper runs.
- **Fix:**
  - (a) `--bus-snapshot` keeps a monotonic `BUS_SNAPSHOT_BUDGET_S` (≤ 25) below the outer bound. Each read gets `min(10, remaining)`. Reads not started in time are recorded `skipped`. The file is always written.
  - (b) AC-5 *requires* the `-` prefix on the `--bus-snapshot` and `--bus-action … unconditional` `ExecStartPre` forms.
  - (c) E-7e(f) AUT-6 maps `bus_snapshot_missing` and `bus_snapshot_stale` to UNKNOWN for health, and to "page" for failed@ and daily.
  - (d) Tests:
    - `test_bus_snapshot_budget_below_outer_timeout_always_writes`;
    - `test_health_bus_snapshot_missing_is_unknown`;
    - `test_failed_notifier_pages_when_bus_snapshot_missing`;
    - a mutation that removes the budget.

**N2. MEDIUM, blocking. E-7e(f): three unlisted `OnFailure=breezy-study-failed@` breaks.**
- **Problem:** AC-5 requires every `OnFailure=` target to be in scope and wrapped, so these units go red at build:
  - AUT-2 r7 l.408, l.423, l.953: the label unit and the slot_guard 255 path;
  - AUT-3 r6 l.267: the refit and reproduce units;
  - AUT-6 r15 l.1046: producer-daily. This contradicts AUT-6's own l.276, which says breezy-autonomy-failed@.
  
  The r3 search found only AUT-1 and AUT-5. This is an L-47-class overclaim of "exhaustive".
- **Fix:** add all three to E-7e(f) (switch to `breezy-autonomy-failed@%n.service`), and to the Consumer Surface table and R10. Re-run the search for `OnFailure=` across all six plans plus AUT-7.

**N3. MEDIUM, blocking. AC-9.1 grammar and E-7e(f): two bus-read consumers cannot be expressed.**
- **(a) AUT-6 health.** The scope includes failed `run-*.service` transients owned by the repo (AUT-6 l.961-962). Reconciliation needs `InvocationID,Result` for them (l.958), and ownership needs `Description` and `ExecStart`. The unit token regex `^breezy-…$` refuses `run-*`. Every failed run-* transient then becomes `journal_blind`, which means UNKNOWN plus a CRITICAL on every pass, or an ownership misclassification.
  - **Fix:** admit the literal glob `run-*` with a fixed property set (`Id,Description,ExecStart,InvocationID,Result,Transient`). List it in E-7e(f) and add a validate_table test.
- **(b) AUT-1 drill.** It refuses unless the recorder is "active with an instance older than 1 h" (AUT-1 l.731). That is a bus read. E-7e(f) gives the drill only `--bus-action`.
  - **Fix:** the drill row gets `bus_reads` (`show -p ActiveState,ActiveEnterTimestamp,InvocationID breezy-quote-tape.service`) plus `bus_snapshot_bind`.
- **(c) Grammar bug.** The selftest row `("-p","Id,ActiveState", …)` (l.313) fails the AC-9.1 grammar as written, because the value after `-p` matches no allowed token.
  - **Fix:** "`-p` must be followed by one token fullmatching `^[A-Za-z,]+$`".

**N4. MEDIUM, blocking. AC-1.3 step 7(c) / AC-5: the studies-lock file is never provisioned.**
- **Problem:**
  - `/run/user/1000` is a tmpfs, so `breezy-studies.lock` disappears on reboot or when the user manager restarts.
  - The wrapper "never creates a bind source", and a missing source gives 78.
  - AC-5 allows only `install -d` and `chmod` in `ExecStartPre`. `install` would also replace the inode, which breaks mutual exclusion.
  - So after every reboot the first `E7_STUDIES_LOCK` row (AUT-6 daily 05:30, AUT-3 refit 06:00) exits 78, until some shell study happens to create the file (`LOCK_DIR` in `deploy/systemd/*-run.sh`).
  - E-7a rule 1 itself says the file is "pre-created", but no owner is named.
- **Fix:**
  - AC-5 admits `ExecStartPre=/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock` on `E7_STUDIES_LOCK` units only. `touch` keeps the inode, and the wrapper's regular-file, owner and nlink checks still run.
  - Add `test_studies_lock_rows_precreate_with_touch_not_install`.

**N5. LOW, non-blocking. E-7e(c) drafting.** Replace E-7a rule 2's test sentence explicitly: "a test fails if a wrapped unit's code references `/proc/locks` or `/proc/<pid>` while its row lacks `host_proc`". Add the namespace-pid hazard from §3.

**N6. LOW-MEDIUM, non-blocking. E-7e(f) / NFR: E-9 recompute per consumer.** Each `--bus-snapshot` or `--bus-action` line adds up to 32 s to its unit's worst case. "Counted by each consumer" (l.241) appears only as an NFR. List the re-check per unit in E-7e(f):
- AUT-1 audit (14:25 bound), drill and guard;
- AUT-6 daily (≤ 06:00Z / ≤ 13:30Z), health (115 s) and failed@.

**N7. LOW, non-blocking. AC-9.1: placement of `bus_snapshot_bind`.**
- The plan uses evidence binds (`evidence/capture/audit`, and evidence/alerts for failed@). That puts non-record files where AUT-6 #23 and the audit's record scanners look.
- Fix: require `bus_snapshot_bind` to be a `cache/…` bind. AUT-1 audit already has its E-8 cache dir.

**N8. LOW, non-blocking. AC-9.2: `{instance}` substitution.** After substitution, the value must fullmatch a unit-name regex, and the argv puts `--` before the units. Otherwise an instance such as `--help` becomes an option. The verbs are read-only, so the impact is small.

**N9. LOW, non-blocking. Consumer Surface l.420 / E-7e(f) AUT-6.** "l.247/251" should read **l.247/250**.

**N10. LOW, non-blocking. WPs.**
- B2c ∥ B3 conflict on more than "one literal": `BWRAP_HOST_TEST_FILES`, the count, `write_sites.py`, `selftest_cli.py` and the AC-5 lint test. Either serialise B2c → B3 or state the full set.
- B2b is large: 7 modules, the script, the harness, the lint, 7 test files and the README. Applying the seam-A A4-R10 precedent (≈ 1,000 lines per gated seam), split it into:
  - B2b-1: table, binds, run_mounts, argv, the wrapper script and the AC-5 lint;
  - B2b-2: self_probe, selftest_cli and the phase-2 namespace file.

**N11. LOW, non-blocking. AUT-2 credential path.** A row field `credential_env: {"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}`, emitted by the wrapper as `--setenv`, is simpler than a "reconcile-only env file (verify-first)". It needs no extra file and no ordering premise. This is the security reviewer's call.

## 6. WP order, tests, LESSONS and path hygiene

- **Order:** B1 ∥ B2a → B2b → (B2c ∥ B3) is sound, apart from N10. There are no hidden dependencies: B3 needs B2b's harness and write_sites, and B2c needs B2b's `bwrap.main`.
- **Gating:**
  - E-7d is filed before B2a and E-7e before B2b. Correct.
  - `--bus-action` is deleted unless E-7e(h) is accepted. Correct.
- **Tests:** there are good mutation lists per WP. Missing are the N1(d), N3 and N4 tests.
- **LESSONS:** I grepped the headers at `/home/jon/breezy/docs/core/LESSONS.md` :8, :620, :685, :1282, :1433, :1495, :1512, :1583, :1647 and :1664. They match the plan's citations. The only violation is L-47 (the "exhaustive" claim; N2, N3). L-1 is a minor note (the `MONITOR_*` refinement in §4). There are no L-12, L-14, L-33, L-43, L-51, L-54 or L-55 violations.
- **Path hygiene:** clean. All paths are literal and absolute, and there is no chatter preamble.

## 7. E-7d and E-7e verdicts

- **E-7d: ADOPT** as written. Rules 1–5, the consumer obligation, the residual and Supersedes are consistent with the plan and the measurements.
- **E-7e: AMEND.**
  - (c): N5.
  - (f): add N2, N3(a)/(b), N1(c) and N6.
  - (h): N1(a)/(b), and N3(c) for the grammar.
  - AC-5 / (c): N4.
  - Once these are applied, I expect to ADOPT without another round. The changes are textual or have a small surface, and none of them reopens a ruling.

Files cited:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r3.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-seamB-r2-architect.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-0-r1-merged.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor.py`
- `/home/jon/breezy/src/breezy/runtime/trade_supervisor_core.py`
- `/home/jon/breezy/docs/core/LESSONS.md`