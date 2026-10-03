# ARCH Rev 9.2 errata (binding on every area plan; the frozen ARCH text is not edited)

Freeze: Rev 9.2, sha 1b288d0e0172b233b791d875845e8002824a52d4a2e7819685ec0f2057572f42.
Scores: architect 97, trading-bot-architect 96, security-reviewer 96. Lowest is 96; zero CRITICAL and zero HIGH.

- **E-1 (architect, MEDIUM): outbox claim order.** First `os.utime` stamps the claim time on the entry. Then an atomic rename into `outbox/claimed/<drainer>/` claims it; the losing renamer gets ENOENT. Never rename then utime. AUT-6 implements this with a concurrency test.
- **E-2 (security, LOW)**: A halt mirror written before the 16:45Z pass starts (for example by the 16:41Z reconcile) is stale by construction for the ROOT_ADMIT check.
- **E-3 (architect, LOW)**: The Rev 9.2 change tags Z1–Z9 are read as `R9.2-Z1…Z9`. Earlier Z labels keep their original meaning.
- **E-4 (security, LOW)**: The failed-canary text belongs under §4.6.

- **E-5 (coordinator, from the AUT-7 r4 architect review H-1; peer-reviewed in the AUT-7 r5 review): restorative RESUME after a failed drill close.**
  - **Trigger:** the drill's closing ROLLBACK fails, leaving the incumbent root HALTED with `ROLLBACK_FAILED` and `trigger_cause_class=DRILL`.
  - **Action:** the 16:45Z pass may write a **restorative RESUME** of that incumbent root, `cause=drill_close_restore`.
  - **Conditions:**
    - The incumbent's artefact and manifest shas re-verify byte-identical.
    - No accepted non-DRILL cause and no exec-store halt names it since the drill's DRILL_PROMOTE.
    - §4.4 preconditions hold.
    - At most one per venue per day, enforced by the store (`drill_close_restores`).
  - **Budgets:** it is charged to NO drill counter and to no production resume budget.
  - **Never:** it never applies to the drill child and never applies after a genuine fault.
  - **Rationale:** the closing step is restorative. A budget must not strand the production incumbent; the venue would otherwise have no sender for ~28 days.

- **E-6 (coordinator, from the AUT-5 r3 reviews R-1 and trading D4; peer-reviewed in the AUT-5 r4 review): the one-time L1 bootstrap.**
  - **What runs:** the single BOOTSTRAP write at the L1 cut-over runs in the STOP→LAUNCH gap as a transient unit, `systemd-run --user --on-calendar='<D> 16:40:05 UTC'`, with `flock -w 10` on the engine lock and `TimeoutStartSec=60`. It never runs as a hand-timed command.
  - **Launch-window table:** it is listed as a one-time row, ending ≤16:41:15Z, before the 16:42:30 intraday pass.
  - **Recurrence:** it never recurs, and the store refuses a second BOOTSTRAP per venue.

## E-7: user-unit mount sandboxing is not enforced on this host

Status: ADOPTED 2026-10-03. Peer-reviewed by security-reviewer (ENDORSE-WITH-AMENDMENTS) and architect (ENDORSE-WITH-AMENDMENTS). Draft and evidence: `E-7-DRAFT.md`.

**Evidence**
- `systemd-run --user -p ReadOnlyPaths=` does not enforce: `touch` succeeds inside the unit.
- `kernel.apparmor_restrict_unprivileged_userns=1`.
- `bwrap --ro-bind` does enforce; the write fails with EROFS.
- `/proc/<pid>/root` escape attempts under bwrap are denied.

**Rules**
1. **Directives are configuration, not controls.** `ReadOnlyPaths`, `ReadWritePaths`, `ProtectHome`, `ProtectSystem`, `PrivateTmp` and `InaccessiblePaths` are configuration only.
   - No plan counts them as enforcement.
   - Tests that parse them are named `*_config_*`.
   - The claim that `ProtectHome` is also a no-op is probable but unverified.
2. **Every unit ARCH grants `ReadWritePaths` runs under bwrap.** This covers two units:
   - The AUT-5 engine binds `registry/`, `evidence/` (including `evidence/alerts`, and `registry/drill/` for AUT-7) and its E-8 cache dir.
   - The AUT-6 `DEMAND_WRITER_PRODUCER_IDS` producers bind only `registry/demand/` and `evidence/alerts`.

   The bwrap invocation is the same for both:
   - Mounts: `--ro-bind / /`, the `--bind` set above, `--dev /dev`, `--proc /proc`.
   - Isolation: `--unshare-pid`, `--new-session`, `--die-with-parent`.
   - Credentials: `--tmpfs ~/.config`, then re-`--ro-bind` only the non-credential files the unit needs. `~/.config/breezy` venue credentials are never visible.
   - Network stays on for outbox delivery. The unit has no import path to the venue adapters, enforced by an import-closure test. NO-SEND is unchanged.

   At start, a self-probe checks both directions:
   - `O_WRONLY|O_CREAT` under `state/` must FAIL.
   - The same open under its own bind (positive control) must SUCCEED.
   
   Otherwise the unit exits INTEGRITY with a delivered CRITICAL.

   Operator CLIs remain a stated residual.
3. **Code-level read-only applies to every other autonomy reader.**
   - SQLite readers use `file:…?mode=ro` with `PRAGMA query_only=ON`. The exception is the engine's exec-store read, which uses E-8.
   - Files are opened `O_RDONLY`.
   - The node's `ReadOnlyPaths` on `registry/` becomes configuration only. The node is never wrapped, and its watch-actor closure is under the AST test.
   - The AST closure test fails on any of these outside the unit's one-writer rows:
     - write-mode `open`
     - `sqlite3.connect` without `mode=ro`
     - `SqliteStateStore(`
     - `subprocess`, `os.system`, `ctypes`, `importlib`

     Every write-authority unit is listed in one table.
4. **What enforces the one-writer property.** bwrap confines only the wrapped units. Against all other same-uid units, the one-writer property rests on the AST closure test plus ARCH's stated residual, and is never described as enforced.

## E-8: engine read of the exec store at 16:45Z

Status: ADOPTED 2026-10-03, peer-reviewed as above. Experiments E1–E3 pass under bwrap.

Only the 16:45 pre-launch pass takes the intent flock. Steps:
1. Open `exec_polymarket_us.sqlite.intent.lock` with `O_RDONLY|O_CLOEXEC`.
2. Take `flock(LOCK_EX|LOCK_NB)`. Never block; retry up to 3 times, 5 s apart.
3. Fingerprint the db, `-wal` and `-journal` as (inode, size, mtime_ns).
4. Copy the db, `-wal` and `-journal` into the 0700 cache dir. Never copy `-shm`.
5. Re-fingerprint. On any change, retry.
6. Release the flock by 16:48:00 at the latest; otherwise record a read failure. A deadline test covers this, and it keeps the 16:50 `_do_launch` intent-lock check clear.
7. Open the copy read-write and run `quick_check`.
8. Read the halt keys and `exec/polymarket_us/intent/current` from the one copy. Decode with the shared `SubmitIntent` decode extracted from `probe_open_intent`.
9. Delete the copy.

Fail-closed rules:
- These count as a read failure, which fails closed: lock held after retries, lock file missing, fingerprint unstable, or `quick_check` failing.
- **Blocking states:** OPEN or `SubmitIntentCorrupt`. `SubmitIntentState` has no AMBIGUOUS member. An absent record does not block.

Other readers and residuals:
- Readers that are not wrapped, such as AUT-2 at 16:41, keep the G6 URI.
- Node-up reads inside bwrap (the advisory 15:30 read) are advisory only and never count toward H.
- The unlocked supervisor write at `trade_supervisor.py:2418` (17:05Z) falls outside the window, and the re-fingerprint guards against it.
- `intent_lock_is_free` is NOT changed (YAGNI; the supervisor is not wrapped, and adoption requires `node_pid == holder`).

This supersedes the AUT-5 r4 `immutable=1` workaround.

Tests:
- `test_exec_snapshot_recovers_stale_wal_after_sigkill`
- `test_exec_snapshot_never_copies_shm`
- `test_exec_snapshot_holds_intent_flock_readonly_fd`
- `test_exec_snapshot_fingerprint_change_retries_then_read_failure`
- `test_exec_snapshot_halt_and_intent_from_one_copy`
- `test_exec_snapshot_missing_lock_file_fails_closed`
- `test_exec_snapshot_releases_by_164800`

## E-7/E-8 consumption by plan

| Plan | E-7 | E-8 |
|---|---|---|
| AUT-3 r6 | Build item: AST read-only test | — |
| AUT-4 r6 | Build item: AST test; rename sandbox-parse tests to `*_config_*` | — |
| AUT-7 r5 | Build item: inherits the engine bwrap; `registry/drill/` in its bind set | Build item: the 16:45 open-intent read uses the E-8 copy, never `probe_open_intent`'s read-write store |
| AUT-2 r7 | Build item: AST read-only test | Keeps the G6 URI and never takes the intent flock |
| AUT-1 | AST test (r8) | — |
| AUT-5 | Owns bwrap and the self-probe (r5) | Owns E-8 (r5) |
| AUT-6 | Demand producers under bwrap; remove the `ReadOnlyPaths` control claims (r8) | — |

## E-9: `TimeoutStartSec` re-arms for each `ExecStart=` command
- **Status:** ADOPTED 2026-10-03.
- **Evidence:** measured by the AUT-6 r9 planner with scratch units on systemd 259.
  - Two `sleep 4` lines under `TimeoutStartSec=5` passed in 8.05 s.
  - With lines of 4 s and 7 s, the unit timed out 5.19 s into the second line.
- **Rule:**
  - A oneshot's worst-case end is the sum of the per-command bounds, plus `ExecStartPre`, plus `TimeoutStopSec`. It is not `TimeoutStartSec`.
  - Every unit with more than one start command must do both of the following:
    - Bound each command with an external `timeout -k`.
    - Compute its worst case from those bounds.
  - Every AUT plan's slot arithmetic uses this rule.
- **Applies to:** a binding build item for every plan. The READY plans (AUT-1, AUT-2, AUT-3, AUT-4, AUT-7) state no multi-command oneshot. Their WP briefs must re-check any `ExecStartPre` or extra `ExecStart` that is added at build time.

## E-10 (coordinator, 2026-10-03; from AUT-5 r7 reviews): two timing readings
- **(a) E-6's `TimeoutStartSec=60`.** The unit sets the literal 60. The wrapper's `timeout -k` (46 s) is the real per-command bound under E-9. Lower per-command bounds inside the 60 s budget comply.
- **(b) The 16:47:30 intraday pass.** When it times out waiting on the lock, it may end at 16:48:01. ARCH's 16:47:50 is replaced by 16:48:01, which is still before the 16:49:00 pre-launch end and the 16:50 LAUNCH. Its worst case is ≤16:49:50.

## E-7a — bwrap every autonomy unit; the AST closure test becomes a lint
Adopted 2026-10-03. Peer-reviewed by architect and security-reviewer, both ENDORSE-WITH-AMENDMENTS; the amendments are merged below. Draft: `E-7a-DRAFT.md`.

### Rule 1: bwrap every autonomy-owned unit
Every autonomy-owned unit runs under one shared wrapper, `deploy/systemd/breezy-autonomy-bwrap`. This includes notifiers and every `OnFailure=` target.
- **Write scope.** Each unit gets `--ro-bind / /`, plus `--bind` on exactly the output dirs listed for it in one table, `AUTONOMY_BWRAP_TABLE`. It also gets the E-7 credentials tmpfs and a self-probe whose negative paths are derived from the table.
- **Wrapper hardening.** The wrapper:
  - resolves its row by unit name and fails closed on an unknown name, with no default row;
  - validates every bind as absolute, existing and free of `..`;
  - runs `exec bwrap --die-with-parent` with no shell interpolation;
  - is a read-only file outside every bind.
- **Tests:**
  - every `breezy-autonomy-*` ExecStart and every `OnFailure=` target goes through the wrapper;
  - an EXDEV positive control.
- **Same-bind rule.** A unit's temp file and final name sit in the same bind.
- **Lock order.** `timeout -k` → `flock -w` → wrapper, or the lock file is pre-created and opened `O_RDONLY`.
- **Notifier fallback.** If bwrap fails to start, the notifier still delivers. Wrapper exit 126/127 is surfaced to the alert path.

### Rule 2: exceptions, kept in the table
- **AUT-2 `reconcile-poststop`.** It keeps GET-only egress and its `EnvironmentFile`. It is exempt only for `venue_positions_read` from the venue-adapter import-closure rule.
- **AUT-3 refit and `reproduce-pm`** (`Type=notify` + `WatchdogSec`). These need `NotifyAccess=all`.
- **`/proc/locks` and `/proc/<pid>` consumers.** These are `aut6.health` and the AUT-6 evaluate stage. They drop `--unshare-pid`, and the table names the exception. A test fails if a wrapped unit's code references `/proc/locks` while its row has `unshare_pid=true`.

### Rule 3: WAL readers
A wrapped unit never opens a live WAL-mode db read-only in place. Under bwrap the result depends on whether sidecars exist: verified, `mode=ro` fails when sidecars are absent, and `immutable=1` loses committed WAL rows.
- **How to read.** Every WAL read under bwrap uses the shared E-8 snapshot helper: copy the db and `-wal` (never `-shm`) into the unit's private cache, under a fingerprint-stable retry, then open the copy.
- **Locking.** The intent-flock step applies only to the exec store.
- **Tests:** "sidecars present" and "sidecars absent", both under bwrap.
- **Rollback-journal stores** (the C5 registry) are unaffected.

### Rule 4: the AST closure test is a lint
The test becomes a defence-in-depth lint with three requirements:
- non-vacuous, with a minimum number of judged call sites per entry point;
- positive controls;
- green at build.

Its completeness is not a READY criterion once the Rule 1 wrapper test passes.

### Rule 5: residual and timing
- **Residual.** These are out of scope and stated as residual:
  - the node, including the in-node AUT-1 capture writers and watch actor;
  - the supervisor, recorder, ingest and operator CLIs;
  - `/proc/<pid>` visibility between same-uid units that lack `--unshare-pid`.
- **E-9 timing.** The wrapper is an ExecStart prefix that adds about 10–50 ms of setup. Timeout sums are re-checked, not re-derived.

### Not part of E-7a: O_TMPFILE
O_TMPFILE is a separate item. The primary data root is on ext4 (`findmnt -no FSTYPE -T ~/.local/share/breezy` → ext4), and O_TMPFILE works there. Plans keep their fallback until WP verify-first repeats the check on the production tree.

### Consumption
| Plan | How E-7a is consumed |
|---|---|
| AUT-1 r8, AUT-2 r7, AUT-3 r6, AUT-4 r6, AUT-7 r5 | Binding build item, with the Rule 2 exceptions already in this erratum. |
| AUT-5 r7 | Binding build item. Coordinator ruling: the engine's bwrap invocation and self-probe are already specified under E-7, so moving them into the shared table is mechanical. The architect recommended a revision; I overrode that because no plan-level decision changes. |
| AUT-6 | Revision r11. |

## E-8a: the shared snapshot helper's API, and node-up exec-store reads
Coordinator ruling, 2026-10-03, from the AUT-6 r11 review.

- **API.** The E-8 helper takes three parameters: `cache_dir`, `take_flock: bool`, and `lock_path`.
  - `take_flock=True` is allowed only for the AUT-5 16:45 pre-launch pass.
  - Every other reader passes `take_flock=False`. That covers every node-up read, including AUT-6's.
  - Those readers rely on the fingerprint-stable retry alone. Their results are **advisory**, consistent with E-8's "node-up reads are advisory": a result never counts toward H and never authorises a widening.
  - E-7a rule 3's "intent-flock step applies to the exec store" means the AUT-5 pre-launch pass only.
- **AUT-5 r7.** Binding build item: add the parameters and a test for each mode.
