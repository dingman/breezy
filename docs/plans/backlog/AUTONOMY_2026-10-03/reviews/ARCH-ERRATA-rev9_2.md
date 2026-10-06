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

## E-7b: venue-adapter import closure for offline replay children (coordinator ruling, 2026-10-03, AUT-4 r7 O-1)

AUT-4's `eval-offline` replay children run `run_live_parity`, which imports `breezy.adapters.polymarket_us.symbology`.

**(a) Required first:** WP1 measures the replay closure. Pure symbology and slug helpers move into an adapter-free module, with delegating shims, following the AUT-6 AF1 precedent. The closure test then passes with no exception.

**(b) Permitted only if the WP1 measurement shows the replay needs non-exec adapter modules** (for example, instrument definitions consumed by the native `BacktestEngine`):
- grant a named E-7a rule-2 exception on the `eval-offline` row only;
- scope it to the measured non-exec modules;
- guard it with `test_eval_offline_closure_has_no_adapter_exec_module` (no `breezy.adapters.polymarket_us.exec*` module, no exec client and no HTTP or WS client in the closure).

**Rejected:** narrowing the E-7 rule generally. This is consistent with the AUT-6 AF1 ruling.

## E-7c: scratch space under the shared bwrap wrapper (coordinator, 2026-10-03, from the AUT-4 r7 MLE review)

- The rule-1 invocation `--ro-bind / /` leaves `/tmp` read-only. Nautilus, pyarrow and `tempfile` scratch writes therefore fail.
- The shared wrapper always adds `--tmpfs /tmp` and sets `TMPDIR=/tmp` for every row. This scratch space is private, discarded at exit, and never a write path for durable state.
- Test: `test_bwrap_wrapper_provides_private_tmp` must confirm all of the following:
  - a write under `/tmp` succeeds;
  - the file is not visible on the host;
  - the state paths still return EROFS.
- Applies to every plan as a binding build item.

## E-11: SELF_HEAL is realised natively by systemd (coordinator, 2026-10-03, from AUT-6 r14/r15)

- **Adopted text.** The exact replacement text is the eight items ER-1..ER-8 in `AUT-6-drift-health_plan_r15.md` §ERRATA-REQUEST, as amended in r15 (ER-1, ER-5, plus the consequential ER-2, ER-3, ER-7, ER-8). Both blind reviewers voted ADOPT: TBA 96 and SFH 95.
- **Substance.**
  - SELF_HEAL is systemd's own `Type=notify` + `WatchdogSec` + `Restart=` on watchdog + `StartLimit*` + `OnFailure=`.
  - A member sends `WATCHDOG=1` only while its liveness counter advances.
  - No autonomy module issues a `systemctl` restart, start or stop.
  - The AUT-6 notifier pages any state it cannot prove is a pending restart.
  - The recorder's incident-backed `StartLimitIntervalSec=0` is a recorded exception. It is bounded by restart backoff, gets a per-kill page via `OnFailure=`, and gets one storm page after 3 kills in a trading day.
  - The launch-window deferral is journaled and alerts WARN once per deferred stall.
- **Dedupe.** E-11 is the single vehicle for the ARCH §4.5/§4.6 SELF_HEAL wording. AUT-1's ER-8 is reduced to recorder-unit-only text.
- **Consumption.** AUT-6 r15, and AUT-1 r10 (recorder side: X-1..X-7 in `reviews/AUT-6-r14-merged.md`).

## E-12: AUT-1 native-first capture (coordinator, 2026-10-03, from AUT-1 r9–r12)

- **Adopted text.** ER-1..ER-10 of `AUT-1-data-capture_plan_r12.md` §ERRATA-REQUEST, exactly as written there. Verdicts:
  - ER-1..ER-7 and ER-10: ADOPT, or AMEND with the amendment already applied.
  - ER-7 includes the per-type and per-write size-delta checks.
  - ER-8 is REDUCED to recorder-unit-only text. The ping source runs from process start; there is a journal cross-check (leg W); E-11 is the vehicle for SELF_HEAL.
  - ER-9 is AMENDED. Its final clause reads: "…recorder and feed stall observations (the recorder's process-level heal is systemd's own watchdog, per §4.6 as amended by E-11; AUT-6 pages and does not restart)".
- **Substance.**
  - C1 is realised by a native `StreamingFeatherWriter` owned by the capture actor (option B), behind a catch-all wrapper.
  - The record types are `@customdataclass` types. No record type has an `instrument_id` field.
  - `ForecastPoint` is streamed natively, and records reference it by `(station, cycle_ns, available_at_ns)`.
  - Frames are referenced in the recorder tape. A Take-path record copies its frame.
  - The payload store, the JSONL writer, FrameClock and the custom watch/watchdog are removed.
  - Loss is bounded at about 61 s (60 s heartbeat plus 1 s flush) and is counted against `SHADOW_DECISION`.
- **Consumption.** AUT-1 r12. AUT-6 r15 build item 7 is consistent.

## E-13: E-7c tmpfs size and the E-7b(a) symbology waiver (coordinator, 2026-10-03, from AUT-4 r9–r11)

- **Adopted text.** ER-1 and ER-2 from `AUT-4-evaluation_plan_r11.md`. Both reviewers voted ADOPT.
- **ER-1 (E-7c).** The shared wrapper passes `--size` before `--tmpfs /tmp`.
  - A row that sets an explicit per-row `tmpfs_size_bytes` gets that size; AUT-4's rows set it explicitly.
  - Any other row gets the wrapper's default cap, so other plans' rows never break.
  - A malformed value fails closed, and a named test covers it.
- **ER-2 (E-7b(a)).** The symbology move is waived when the WP1 measurement shows it buys nothing, because the closure still reaches symbology via `fees`, `parsing` and `symbology`. The waiver:
  - applies to the eval-offline row only;
  - requires the WP1 measurement and the (b) guard tests to be green;
  - never reaches `order_enablement` or `exec*`;
  - does not waive (b)'s "needs" condition.


## E-7d (coordinator, 2026-10-03, from ARCH-0 seam B r5): the gate runs real-namespace tests in an un-nested second phase.
- **Evidence.** Nested bwrap inside the gate fails ("No permissions to create a new namespace", apparmor `bwrap-userns-restrict`), while one level works. On pytest 9.1.1:
  - a `-p` plugin's `pytest_load_initial_conftests` runs before any conftest import and can exit rc 2;
  - `pytest_ignore_collect` keeps non-registry conftests and modules unimported;
  - a `-p` plugin also named in `pytest_plugins` loads once;
  - `PYTEST_PLUGINS` imports its module before the early hook;
  - `-p no:<plugin>` blocks a `-p` plugin.

  With the blocker and four conftest edits, the phase-2 parent loaded no `nautilus_trader*` or `breezy.adapters*` module.
- **Rule 1: one gate, two phases.** `scripts/ci/run_tests_no_egress.sh` remains the gate.
  - Phase 1 is the existing egress-blocked pytest, run with `-p tests.support.bwrap_host_phase`, selected by one `if bwrap / elif unshare / else exit 3` chain and run exactly once.
  - Phase 2 then runs un-nested. The gate prints both exit codes and exits with the first non-zero.
  - Phase 2 is omitted only when an exact argument token is `--collect-only`, `--co` or `--collectonly` **and** the mode-0600 confirm file that the script created with `mktemp` under the gate dir reads exactly `collect-only`. Phase 1's plugin writes that file from pytest's parsed `collectonly` option.
  - A missing, empty or `run` confirm file runs phase 2, so disabling the plugin by any means (`--noconftest`, `-p no:…`, `PYTEST_ADDOPTS`) cannot skip phase 2. A token claim while pytest is not in collect-only mode exits rc 2.
  - On a host where only `unshare` works, phase 1 runs and phase 2 refuses with rc 3, so the gate is red there by design.
  - Phase 2's basetemp is a fresh `mktemp -d` under the gate dir; it and the confirm file are removed on exit.
- **Rule 2: what phase 2 runs.**
  - Exactly `tests.support.bwrap_host_phase.BWRAP_HOST_TEST_FILES` with `-m bwrap_host`. The set is exact and equals the AST-derived set of marker users.
  - The passed count must equal the mutation-pinned literal `BWRAP_HOST_EXPECTED_TESTS`. A plan adding a real-namespace test widens both in the same commit (L-12).
  - Phase 1 skips `bwrap_host` items with a reason naming phase 2. In phase 2, any skip, any item outside the set, or a count mismatch fails the session.
  - The first merge ships a self-contained witness file as the only member.
- **Rule 3: prevention in the parent.**
  - Phase 2 runs with `BREEZY_BWRAP_HOST_PHASE=1` and `-p tests.support.bwrap_host_phase`, under `env -u` of `BREEZY_TEST_OS_EGRESS_BLOCK`, `BREEZY_GATE_COLLECT_ONLY_CLAIM`, `BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE`, `PYTEST_PLUGINS` and `PYTEST_ADDOPTS`. User arguments are never forwarded.
  - The plugin puts a meta-path blocker at `sys.meta_path[0]` before any conftest loads. The blocker refuses `nautilus_trader*`, `breezy.adapters*` and the module of every `find_execution_egress_modules()` hit.
- **Rule 4: N2, widened as an exact set.** `execution_egress_abort_reason` gains one keyword-only input; when it is absent, the rule is unchanged. An unattested session is admitted only if:
  - (1) the variable is exactly `"1"`;
  - (2) the attestation is absent;
  - (3) the blocker (exact class) is at `meta_path[0]`;
  - (4) every egress hit maps to a refused module;
  - (5) no refused module is loaded;
  - (6) the plugin was loaded with `-p`, and before any conftest import it found every positional argument inside the registry, no option that widens collection (`--rootdir` other than the repo, `--confcutdir`, `--noconftest`, `--pyargs`, `-c`/`--config-file`, a non-default `--import-mode`, or any `-p` beyond the plugin, `no:randomly` and `no:cacheprovider`), and neither `PYTEST_PLUGINS` nor `PYTEST_ADDOPTS` in the environment;
  - (7) `pytest_ignore_collect` excludes every non-registry file and every directory that is not an ancestor of one.

  Anything else aborts with rc 2. A variable set to any other value, including `""`, `"true"` or `"1 "`, aborts with rc 2; this differs from today only when the variable is set. Attested plus the phase variable aborts with rc 2. The credential gate runs first and is unchanged. The session end re-checks `sys.modules`. No canary is sent in phase 2.
- **Rule 5: children and imports.** Every bwrap child a phase-2 test spawns goes through `tests/support/bwrap_harness.py`, which adds `--unshare-net` and an explicit environment. An AST lint covers the registry files and every `tests.support` module they import:
  - denied imports: `socket`, `http*`, `urllib*`, `requests`, `httpx`, `aiohttp`, `websockets`, `ctypes`, `runpy`, `nautilus_trader*`, `breezy.adapters*`, `breezy.strategy*`, and `subprocess` except in the harness;
  - denied calls: `os.exec*`, `os.spawn*`, `os.system`, `os.popen`, `os.fork`, `importlib.util.spec_from_file_location` and `SourceFileLoader`.
- **Consumer obligation.**
  - Nautilus work in a phase-2 test runs only inside a bwrap child.
  - Phase-2 files live outside `tests/unit/` and `tests/contract/`.
  - A receiver a child must reach runs inside that child's namespace.
  - A phase-1 test may start bwrap through `systemd-run --user`; such a unit runs outside the gate's network namespace, so its argv is literal, stdlib-only and imports no `breezy` module.
- **Residual.** The phase-2 parent has host network for native non-Nautilus code. Python sockets stay blocked by the conftest fixture. File-path module loading is covered by the Rule 5 lint. A `PYTEST_PLUGINS` module set by a caller who bypasses the script imports before any check; the script's scrub is the control. Phase 2 runs `python -m pytest` without `-I` because worktrees need `PYTHONPATH`; a caller-controlled `PYTHON*` variable or `sitecustomize` imports before the blocker. This is operator-controlled environment, the same exposure as phase 1.
- **Supersedes** B-R1's "Phase 2 collects `-m bwrap_host tests/`" and AUT-5 r7 l.287's verify-first branch. **Security sign-off:** ARCH-0 seam B r3 security review, YES-WITH-CONDITIONS, with C-1 and C-2 folded in above; seam B r4 security and architect reviews, ADOPT, with the r4 security N2 residual sentence added above. **Filed before** WP-B2a merges.

## E-7e (coordinator, 2026-10-03, from ARCH-0 seam B r5): ARCH-0 owns the shared wrapper, table, self-probe, bus snapshot handoff and E-8 helper.
- **Ownership.** ARCH-0 seam B owns `deploy/systemd/breezy-autonomy-bwrap`, `AUTONOMY_BWRAP_TABLE` and its validation, the self-probe, the bus snapshot handoff, the E-8 helper (`wal_snapshot`, `exec_snapshot`) and the E-7a rule-1 unit lint. They live in `src/breezy/runtime/autonomy_sandbox/`, under the forbidden contract `breezy.runtime.autonomy_sandbox ↛ nautilus_trader, breezy.adapters, breezy.strategy` (`allow_indirect_imports=false`). This is a stated deviation from ARCH §3's "types live in persistence/autonomy". AUT-5 keeps the halt and intent decode, the 16:48:00 value, the E-8 test names and its rows. In the E-7/E-8 consumption table, the AUT-5 "owns" entries move to ARCH-0.
- **(a) Write-authority allowlists.** AUT-5 r7 l.292's `exec_snapshot.py` and `sandbox_probe.py` rows are replaced by `SHARED_WRITE_SITES`, admitted only when every snapshot call passes `cache_dir=` a module-level `Final` constant of the caller.
- **(b) E-8 amendment.**
  - Fingerprint: (inode, size, `mtime_ns`) plus sha256 of db bytes 0–99, `-wal` bytes 0–31 and its last 4096, `-journal` bytes 0–511; a 20 ms quiescence wait.
  - Copy order db, `-wal`, `-journal`, fd-relative, into `snap.*` under an `O_RDONLY|O_DIRECTORY` cache-dir flock; contention gives `cache_busy`.
  - Non-advisory only if the intent flock was held throughout.
  - `take_flock=True` only in the AUT-5 16:45 pass, after the day's STOP_PRIOR decision line, with a deadline before 16:50. A STOP_PRIOR that starts during the hold refuses with one false CRITICAL and no signal (residual).
- **(c) Mount-set amendment to E-7 rule 2 and E-7a rules 1, 2 and 5.** Every row runs:
  - `--unshare-user --disable-userns --assert-userns-disabled --unshare-pid`;
  - `--ro-bind / /`, `--tmpfs /run`, `--dev /dev`;
  - `--proc /proc` except on `E7A_R2_PROC` rows, which keep `--unshare-pid` and see the host procfs read-only through the root bind (locks, status and cmdline readable; environ and root EACCES; signals to host pids ESRCH);
  - `--size N --tmpfs /tmp`;
  - `--tmpfs ~` with ro re-binds of exactly the repo, the data root, the interpreter prefix and, on `E7_FIXTURE_ROOT` rows, the alternate base;
  - the exact per-row `/run` re-binds: resolv target (`resolves_dns`), `NOTIFY_SOCKET` (`E7A_R2_NOTIFY`), `/run/user/<uid>/breezy-studies.lock` (`E7_STUDIES_LOCK`) and `$CREDENTIALS_DIRECTORY` (`E7A_R2_RECONCILE`), then `--remount-ro /run`;
  - `--bind-fd` binds after a nofollow walk, distinct from `state/` and its ancestors; `--ro-bind-fd` config; `~/.config/systemd/user` only under `E7_CONFIG_DIR`;
  - `--remount-ro ~`;
  - `--setenv TMPDIR /tmp --setenv XDG_CACHE_HOME /tmp/.cache`, `--unsetenv BREEZY_AUTONOMY_SANDBOX_DEGRADED`, and on `E7A_R2_RECONCILE` rows `--setenv <VAR> $CREDENTIALS_DIRECTORY/<name>` for each `credential_env` item. `credential_env` keys must additionally not be `PATH`, `HOME`, `TMPDIR`, `XDG_*`, `LD_*`, `PYTHON*` or `BREEZY_AUTONOMY_*`; `validate_table` rejects them.

  This replaces E-7a rule 2's "drop `--unshare-pid`". **E-7a rule 2's test sentence becomes:** "A test fails if a wrapped unit's code references `/proc/locks` or `/proc/<pid>` while its row lacks `host_proc`." **Rule:** on `E7A_R2_PROC` rows, never index `/proc` by a namespace pid (`os.getpid()`, `Popen.pid`); those name other host processes. Rule 5's `/proc/<pid>` residual narrows to read-only status and cmdline visibility. No row exposes `/run/user/<uid>/bus`, `/run/user/<uid>/systemd/private`, docker, snapd, lxd or the system bus. The unit check is integrity against misconfiguration, not an authorisation boundary. The wrapper never creates a bind source, including the studies lock.
- **(d) Self-probe amendment to E-7 rule 2.**
  - The env-row check runs before any open.
  - Negatives come from the table only, with an owned-directory precondition and exactly EROFS on `O_TMPFILE|O_WRONLY`; no named file is created under `state/`, the data root or the repo.
  - Positives are `tmpfile`/`subdir`.
  - Credential paths give ENOENT, and the home listing is ⊆ the re-binds.
  - Host and bus sockets give ENOENT; `/run` is allowlisted and read-only.
  - pid namespace: `/proc/1/comm == "bwrap"`, or on `E7A_R2_PROC` rows `/proc/self` ≠ `getpid()`. This is an integrity check, not a boundary.
  - Vocabulary: AUT-6's codes plus `env_row`, `degraded_forged`, `credentials_visible`, `user_bus_visible`, `host_socket_visible`, `run_not_private`, `run_not_readonly`, `tmp_not_private`, `pid_ns`, `negative_unverifiable`.
- **(e) Labels.** `KNOWN_EXCEPTIONS = {E7A_R2_PROC, E7A_R2_NOTIFY, E7A_R2_RECONCILE, E7B_EVAL_OFFLINE_ADAPTER_MODULES, E7_CONFIG_DIR, E7_STUDIES_LOCK, E7_FIXTURE_ROOT}`. There is no user-bus label and no bus-action label.
- **(f) Consumer changes (binding build items).**
  - **Every plan:**
    - an owned unit's `OnFailure=` names `breezy-autonomy-failed@%n.service`, never `breezy-study-failed@`. This supersedes ARCH §5.2 l.1066's `OnFailure=breezy-study-failed@` for autonomy-owned studies (E-7a rule 1); AUT-2 l.1199 is amended accordingly;
    - `resolves_dns=True` on every row that can deliver an alert, each with a test;
    - E-9 sums count every pre line at `T + K` (`TimeoutStartSec` re-arms per command), and each pre line's bound is below the unit's `TimeoutStartSec`. In the AC-5 form-1 shape (`timeout -k 1 4`, AUT-5 r7 l.259) an `install -d` line counts 5 s; the `touch` line counts 5 s; a bus-snapshot line counts `B + 5`.
  - **AUT-1 r12:**
    - l.770/939: the audit's `systemctl --user show` becomes a bus read (budget 10, a `cache/` bind; a missing snapshot is never a pass); l.768-769: journalctl in-sandbox;
    - l.731/733/741/883-884/941: the drill and guard run **unwrapped**, listed in `UNWRAPPED_RESIDUAL_UNITS` as an E-7a rule-5 residual, with no socket bind. Re-wrapping re-files with `--kill-whom=main`, the bus-snapshot directory discipline, SIGCONT on every exit path and a target set with plan:line;
    - l.875 is amended accordingly; l.1045: V-9(b) becomes the handoff;
    - l.905-906: `OnFailure=breezy-autonomy-failed@%n.service`, and the `alerts.env` re-bind is removed;
    - l.881: `flock -w %t/breezy-studies.lock`;
    - the stop-hook unit is linted on its wrapper line only; l.125/886 rotate is unchanged;
    - E-9: audit latest end 13:50 + 60 s + 15 s + 1500 s + 5 s = 14:16:20 (plus `T + K` of any `install -d` pre line, ≤ 5 s: ≤ 14:16:25) ≤ 14:25. The `flock -w 600` runs inside ExecStart's `timeout` (≤ 1500), so it is not added; AUT-1 l.881 is restated on this basis.
  - **AUT-2 r7:**
    - l.180/468: reconcile is `E7A_R2_RECONCILE` with `LoadCredential=`, `credential_names=("polymarket_us_secret_key",)` and `credential_env={"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}`, and the caller passes the existing `require_key_file_mode=0o400` (`env.py:98`). The inline-key variable is absent (otherwise the loader fails closed). No `env.py` or firewall-test change is permitted. Reconcile stays GET-only (consumer test). `resolves_dns=True`.
    - l.408/953: label unit `OnFailure=breezy-autonomy-failed@%n.service`; l.1199's "The label unit keeps `OnFailure=breezy-study-failed@` (the §5.2 studies rule)" is amended to `breezy-autonomy-failed@%n.service` per "Every plan"; l.423/463/1188: the `breezy-score-live-trials` slot-guard path is unchanged (not owned).
    - l.470/485/1054: `breezy-aut2-recon-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
    - l.467: `%t/breezy-studies.lock`; wrapped G6 reads use `exec_snapshot(take_flock=False)`.
  - **AUT-3 r6:**
    - l.267: `NotifyAccess=all` and `OnFailure=breezy-autonomy-failed@%n.service` on refit and both repro units;
    - l.279-283/292: `E7_STUDIES_LOCK` with `ExecStartPre=-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock` (+5 s; reproduce-am `TimeoutStartSec` 4139 → **4134**, so 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z, and the AM eligibility threshold becomes `runtime_s × 1.2 + 600 ≤ 4134`, i.e. `runtime_s ≤ 2945`; AUT-4's K8 test sums pre lines.)
    - l.296: the repro extract moves to `cache/refit-repro/`;
    - l.190/282-283: wrapped transients pass `--unit=<row unit>` and use the literal lock path.
  - **AUT-4 r11:**
    - l.661/1228/1401: `E7_FIXTURE_ROOT`;
    - l.848/871/888/892/898: both integration files join the registry;
    - l.875-884: `WRAPPER_CODE_FILES` and `build_bwrap_argv`;
    - l.634-635/664: `%t/breezy-studies.lock` via `flock -w` (no pre-create);
    - l.642 (K8): `test_pre_offline_studies_units_end_by_1045z` sums every pre line at `T + K`;
    - l.637/848/1311: unchanged;
    - E-13 tests are delivered by ARCH-0 at AUT-4's paths.
  - **AUT-5 r7:**
    - l.278-282: wrapper rows `breezy-autonomy-engine@<mode>` with exact instance names, the bootstrap `derived/artefacts`, and the stage-S rows;
    - l.202/286: `require_sandbox`;
    - l.277: `OnFailure=breezy-autonomy-failed@%n.service`;
    - l.284: the table-derived config test;
    - l.285/405/879-880: registry;
    - l.292: `SHARED_WRITE_SITES`;
    - l.386-388: `exec_snapshot(False)`;
    - E-8: the STOP_PRIOR-line precondition;
    - l.259/279/273-275: unchanged.
  - **AUT-6 r15:**
    - l.203-207/802/958/966: `systemctl` reads become `--bus-snapshot` with `--` before units, on new `cache/aut6_health_bus` and `cache/aut6_failed_bus` binds plus daily's `cache/aut6_daily_exec_snapshot`; budgets health 15, failed@ 10, daily 15. The health `show -p <fixed set> -- 'breezy-*'` result also lists timers and slices, so the consumer filters on `Id` ending `.service` (with a consumer test).
    - l.961-962: failed `run-*` transients through `RUN_TRANSIENT_SHOW_ARGV`.
    - Mapping: `bus_snapshot_missing`/`_stale` → health UNKNOWN (`passes_unknown_streak` increments); failed@ and daily page CRITICAL. A per-read failure keeps l.488/l.957. Tests `test_health_bus_snapshot_missing_is_unknown`, `test_failed_notifier_pages_when_bus_snapshot_missing`, `test_daily_pages_when_bus_snapshot_missing`.
    - E-9:
      - health ≤ start + `T+K`(install) + 20 + 115 + 5 s (≤ start + 145 s); **this erratum amends ARCH §5.2 l.1089 `aut6.health` to '≤ 145 s | start + 145 s'**. The 16:31/16:41/16:51/17:01 passes end ≤ +146 s from the slot, before the next slot, and the pass is read-only. `HEALTH_PASS_BUDGET_S=90` is unchanged. (ARCH l.1089 today reads "≤ 120 s | start + 120 s". AUT-6 l.1037 and l.1061 are restated to slot + 146 s, and l.1064 to 05:55:36Z / 13:25:36Z, e.g. the 16:41 pass ends ≤ 16:43:26.)
      - failed@ runs `T+K`(install) 5 s + snapshot (`timeout -k 2 13`) 15 s = ≤ 20 s before its page; AUT-6 l.1053's 'ends ≤ start + 61 s' becomes '≤ start + 81 s' (the AUT-6 owner re-derives it from the unit file via `start_phase_bound_s`).
      - daily ends ≤ 05:30:00 + 1 (accuracy) + 5 (install) + 5 (touch) + 20 (snapshot, `timeout -k 2 18`) + 1500 (ExecStart; the 300 s lock deadline is inside it) + 5 (`TimeoutStopSec`) = 05:55:36Z, and likewise ≤ 13:25:36Z, inside "ends ≤ 06:00Z and ≤ 13:30Z".
    - l.1174: V-6 expects in-row `systemctl` to fail and the snapshot to equal the outside reads.
    - l.247/250: `E7A_R2_PROC`.
    - l.249/671: `E7_STUDIES_LOCK` on `/run/user/<uid>/breezy-studies.lock` with the `touch` line and a path test; l.1071: `IN_PROCESS_STUDIES_LOCK_UNITS` derived from the table rows with `studies_lock=True`.
    - l.249/1444: `E7_CONFIG_DIR`; l.241-243/1334: home-allowlist and `/run`-set assertions; l.260-262: `O_TMPFILE` negatives.
    - l.1335-1338/1349/1356-1357/1375-1376: move to `tests/integration/test_integrity_floor_bwrap_namespace.py` (registry), with the l.1357 receiver in the child; l.1150/1228/1400: registry; l.1377/1292/2290: phase 1.
    - l.276/1046: producer-daily `OnFailure=breezy-autonomy-failed@%n.service`; l.1027: recount the multi-command units (health 2 pre lines, failed@ 2, daily 3) via `start_phase_bound_s`.
    - `breezy-autonomy-failed@` joins `NOTIFIER_FALLBACK_ROWS`.
- **(g) Notifier fallback.** Only rows in `NOTIFIER_FALLBACK_ROWS` may fall back, only after every configuration check, with a 2 s preflight. `degraded_write_target` refuses `state/` and anything outside the binds, and the consumers' closure tests enforce its use. Degraded mode exposes `~/.config/breezy` (residual).
- **(h) Bus snapshot handoff.**
  - **No bus inside any sandbox, and no state-changing bus call anywhere in ARCH-0.**
  - A row's literal `systemctl --user show|list-units|list-timers` argvs, which must follow the grammar (`-p` + one `^[A-Za-z,]+$` token; `--` before unit tokens; unit tokens `^breezy-[a-z0-9@._*-]+$` or a re-validated `{instance}`; `run-*` only as the exact `RUN_TRANSIENT_SHOW_ARGV`), run unsandboxed through `ExecStartPre=-/usr/bin/timeout -k 2 <B+3> …/breezy-autonomy-bwrap --bus-snapshot <row>` as the last pre line, with `B + 5 < TimeoutStartSec`. They run only after every wrapper configuration check.
  - A monotonic budget `B ∈ [1, 25]` bounds all reads; each read runs in its own session and is process-group killed on timeout; unstarted reads are recorded `skipped`; the file is always written.
  - The file is created through a validated `O_DIRECTORY|O_NOFOLLOW` fd on `.bus_snapshot` inside a `cache/` bind (owner, mode, device and forbidden-inode checks). It is keyed by `$INVOCATION_ID`, read and unlinked by the sandboxed step, and swept after 24 h only for regular files named `^[0-9a-f]{32}\.json$`.
  - A failed pre step never skips the main step (`-` prefix), and the main step maps a missing or stale snapshot per (f).
- **(i) Residuals.**
  - Same-uid hostile processes are out of scope.
  - `E7A_R2_PROC` rows read other same-uid processes' `/proc/<pid>/status` and `cmdline`, at parity with unwrapped (no `hidepid`).
  - Abstract unix sockets and loopback are shared, because the network namespace is shared; DNS rows reach the `127.0.0.53:53` stub.
  - The ro-bound repo exposes git-ignored repo-root files, including the operator caps file (no credential, never read).
  - `E7A_R2_RECONCILE` rows see their own loaded credential copy.
  - AUT-1's drill and guard run unwrapped (`UNWRAPPED_RESIDUAL_UNITS`).
  - The studies-lock `touch` line updates the lock's mtime; nothing depends on it.
- **Sign-off:** ARCH-0 seam B r3 security rulings (a)–(c) and (e)–(g) accepted, (d) applied by removal; architect r3 AMEND items applied; seam B r4 security and architect reviews ADOPT-WITH-AMENDMENT, with the amendments applied above (architect B-1 and B-2 verbatim, the ARCH l.1066 supersede clause, the security N1 key denylist). **Filed before** WP-B2b-1 merges.

## E-14 (coordinator, 2026-10-03; from ARCH-0 seam A r1–r5 and the r1–r4 architect and security reviews): per-family root records.
- **Defect.** ARCH C3 "Bootstrap roots" (line 261) writes one `root.json` per `derived/artefacts/<model_class>/<sha>/`. `pm_us_crh_v4` and `pm_us_crh_cont` are both `continuous_rung_hold` with `density_artefact_sha256 = 247f636350685b38966251703c47d10531913367fbcca175b086a2c298421a65` (the `not_applicable_density.json` placeholder) and both are RETIRED seeds (line 738). Their `root/v1` bodies differ in `family_id` and `manifest_sha256`, so the second write-once returns EXISTS_DIFFERENT and the genesis BOOTSTRAP cannot complete. Separately, ARCH lines 263-264 expect the committed root file to change after bootstrap, which, once the resolver binds a root to its committed bytes, leaves the venue without a sender at the next LAUNCH.
- **Rule.**
  1. A root copy is written to `derived/artefacts/<model_class>/<sha>/artefact.json` (0444) and `derived/artefacts/<model_class>/<sha>/roots/<family_id>.json` (0444, `root/v1`, fields unchanged). This replaces `<sha>/root.json` in ARCH C3 line 261, AUT-5 r7 §3.2 lines 172 and 180, and AUT-7 r5 line 41 and `test_rollback_to_root_reads_content_addressed_copy` (line 569).
  2. A root copy's model class is `f"{composition_kind}:{ROOT_ARTEFACT_COMPONENT}"` with `pins.ROOT_ARTEFACT_COMPONENT = "density_table"`; a root's artefact is its manifest's density artefact.
  3. **Scope: families whose introducing row is BOOTSTRAP or ROOT_ADMIT with `lineage_root_family_id == family_id` ("roots"), whatever the authorising kind (BOOTSTRAP, ROOT_ADMIT, ROLLBACK, RESUME).** A family introduced by any other kind, or a BOOTSTRAP/ROOT_ADMIT row with `lineage_root_family_id != family_id`, invalidates the chain. For a root the resolver (a) reads the manifest only from `deploy/families/<family_id>.json` in the repo (never a registry copy) and refuses `manifest_sha_mismatch` unless its sha256 equals `row.manifest_sha256`; (b) reads `roots/<row.family_id>.json` and refuses `root_record_mismatch` unless `record.family_id == row.family_id`, `record.manifest_sha256 == row.manifest_sha256`, `record.artefact_sha256 == row.artefact_sha256`, and `record.committed_path == "deploy/families/" + family_id + ".json"` exactly. Children are out of scope: a Y2 no-new-lineage child resolves `artefact.json` in the existing `<sha>/` directory and has no `roots/` record; a new-lineage child is bound by its C3 `lineage.json`.
  4. A second root sharing a `<sha>` directory writes `artefact.json` as an EXISTS_EQUAL no-op. EXISTS_DIFFERENT on `artefact.json` or on a `roots/<family_id>.json` is INTEGRITY.
  5. The `<sha>/` and `roots/` directories become 0500 after the genesis transaction's last copy. This is hygiene, not a control (same-uid residual). A new file in a 0500 directory is refused by mode bit (`DIR_NOT_WRITABLE`), so AUT-3 refits write `artefact.json` and `lineage.json` into a fresh `<sha>/` only, never into a root's directory.
  6. **Order and idempotence.** Every copy is written before the genesis BOOTSTRAP COMMIT. A crash and rerun is idempotent: an existing file with equal bytes is EXISTS_EQUAL, decided by reading it before any temp file is created, so a rerun succeeds even after the rule-5 chmod.
  7. **Frozen committed root bytes.** Once a root is bootstrapped or root-admitted on any registry root (production or shadow), its `deploy/families/<family_id>.json` bytes are frozen. `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256` (a `MappingProxyType` of `family_id → sha256`, empty until the reviewed pins commit that precedes the first bootstrap, which lists every `BOOTSTRAP_SEED` id; a ROOT_ADMIT adds its row in the same commit as its allowlist triple) pins them. Rows are append-only. `test_bootstrapped_root_manifests_unchanged` fails CI on any edit, so the failure lands at merge rather than at LAUNCH. Superseding a bootstrapped root, including setting `terminal_climate_day`, is done in the registry (RETIRE) or by a new root (a new `family_id` through ROOT_ADMIT), never by editing the committed file. **Clearing path (L-48)** if an edit reaches a running tree anyway (resolver `manifest_sha_mismatch`, no sender, entries vetoed): a reviewed revert restoring the pinned bytes, or ROOT_ADMIT of a new root. ARCH lines 263-264 ("even if the repo file changes") are refined accordingly: ROLLBACK to a root still reads the store artefact, but the root's committed manifest bytes must equal the row. **[r5]** Until ROOT_ADMIT is enabled (it is not at L1), the reviewed revert is the only clearing path, and from the stage-S bootstrap onward the live `forecast_quantile_ladder` root manifest is frozen; the CI pin test is hygiene, and the runtime anchor is the resolver's `manifest_sha_mismatch`.
- **Consumption.** ARCH-0 seam A (`paths.root_record`, `family_bytes.write_root_copy`, the resolver, `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, `single_read` `DIR_NOT_WRITABLE`); AUT-5a bootstrap and the pre-bootstrap pins commit; AUT-7 r5 root reads; AUT-3 refit destinations. Fail-closed until filed: BOOTSTRAP refuses and nothing goes live.

**Plan amendments recorded with E-14.** The complete list of ARCH and consumer-plan text that ARCH-0 seam A amends is `ARCH-0-seamA_plan_r5.md` §ERRATA-REQUEST (b) items 1–46, as modified by that plan's "Coordinator amendments to r5" (A6-R1, A6-R2). Consumer plans read those items as binding alongside this erratum.

## E-15 (coordinator, 2026-10-03; from the ARCH-0 seam B WP-B2b-2 security review): per-row network namespace
- **Finding.** The autonomy bwrap argv shares the host net namespace on every row. That leaves abstract AF_UNIX sockets (dbus, X), which `/run` masking cannot hide, and all egress reachable from every wrapped unit.
- **Ruling.** ARCH-0 seam B adds `--unshare-ipc/-uts/-cgroup-try` (B6-R8) but does not decide network policy. Each consumer plan that adds a row (AUT-1, AUT-2, AUT-5a, AUT-6) must state, per row, whether it needs network egress. Rows that need none get `--unshare-net` through a new required row field. AF_UNIX path sockets such as NOTIFY_SOCKET stay reachable through their binds. The field and its argv emission land in the first consumer WP that adds a non-egress row.
- **Fail-closed reading.** Until a row declares the field, a reviewer treats a missing declaration as a review blocker for that row.

## E-16 (coordinator, 2026-10-04; from the ARCH-0 seam A 6b ARCH review): pair citation, root introduction, pending-head integrity
- **(a) ACTIVATE cites its pair.** ARCH l.418 currently says `paired_transition_id` is non-null only on "the partner of an atomic pair". Amendment: it is also non-null on ACTIVATE, where it holds the `transition_id` of the →CHAMPION pair head being activated. The head must share `family_id` with the ACTIVATE, and the ACTIVATE must be written in [STOP, LAUNCH) on the head's `effective_launch_date` (ARCH:453, :482). Column rules in seam 6e and `validate` in 7c/7d follow this reading.
- **(b) Root introduction.** The ALLOWED table (ARCH:468, :479) gains `ROOT_ADMIT: (∅, CHAMPION)` for a family unknown to the fold (plan r5:200, ruling A4-R6). A pending introducing ROOT_ADMIT shows the family as SHADOW until its pair takes effect.
- **(c) Pending-head integrity.** A PROMOTE, DRILL_PROMOTE, ROLLBACK or ROOT_ADMIT row with `to_state=CHAMPION` and a null `effective_launch_date` makes the fold return `FoldInvalid(head_missing_launch_date)`. This value is added to the closed `FoldInvalidReason` set.
- **(d) Widening is decided per row.** WIDENING is decided per row, not per kind: a PROMOTE widens only toward CHAMPION (AUT-5 r7:166). Stage gating therefore never refuses a SHADOW→CHALLENGER nomination.

## E-17 (coordinator, 2026-10-04; from the ARCH-0 seam A 6e database and ARCH reviews): registry store write semantics
- **(a) Y9 replay compares bodies.** A row whose `transition_id` exists is a logged no-op only if its stored body equals the submitted one on every semantic column. The excluded columns are `seq`, `venue_seq`, `ts_ns`, `invocation_id`, `expected_prior_seq` and the chain hashes. A mismatch is refused as `ReplayMismatch`. A submitted `transition_id` must equal the id computed from the row.
- **(b) Durability.** The registry writer uses `PRAGMA synchronous=EXTRA`, not FULL. In DELETE journal mode only EXTRA fsyncs the directory after the commit-point journal unlink. This amends ARCH Y5 and AUT-5 r7 §3.2.
- **(c) Clock.** A row's `ts_ns` must not exceed the writer's clock. The old symmetric ±300 s skew window becomes one-sided, so that the fold's `ts_ns <= now_ns` application can never delay a committed restrictive row.
- **(d) Write order.** CAS on `expected_prior_seq` runs before the clock check. A stale writer then sees `CasMismatch` and takes the ARCH l.530 re-read/retry path, rather than `clock_before_head`.

## E-18 (coordinator, 2026-10-04; from the ARCH-0 seam A 6f/7e ARCH review): registry exports
- **(a) Full-history exports.** Every daily and `_hwm<k>` export carries all rows of its venue from `venue_seq` 1 through the trailer row, contiguous and hash-linked. The "rows since the previous export" reading (ARCH l.437, AUT-5 r7:173) is withdrawn. The reasons:
  - AUT-5 r7:154 (B9) folds the newest export for counter floors.
  - Reset-CLI step 2 compares against "rows in that export".
  - Both need the full history in one file.
- **(b) Corrupt-export incident path.** A candidate under `evidence/registry/` that does not read as a valid export makes `newest_export` refuse. That blocks the resolver, the watch actor and reset-CLI step 1, by design. Exports stay append-only in normal operation. The only clearing path is an AUT-5a-owned incident procedure, which runs in this order:
  1. File an incident report naming the file, its sha256 and the cause.
  2. Move the file into a quarantine directory outside `evidence/registry/` (never delete it).
  3. Run the HWM reset CLI.
  AUT-5a owns the procedure, its CLI and its test.

## E-19 (coordinator, 2026-10-04; from the ARCH-0 seam A 7a ARCH review): fold flag scoping and the post-launch cause path
- **(a) Y8 in the post-launch window.** From LAUNCH to the launch-window end (17:00), a cause on the incoming family of an activated pair is written only as SWAP_CANCEL `pair_cause_incoming`. That voids the pair and restores the incumbent. `validate` refuses a DEMOTE or HALT of that incoming family in this window. A HALTED child plus a CHAMPION incumbent would otherwise be two senders, and a single-sender check would then refuse a restrictive batch.
- **(b) `demoted_for_cause` is per champion epoch.** It holds only for causes inside the family's current champion epoch, and RESUME opens a new epoch (AUT-7 r5:105-109). ARCH:493's "never cleared" is read at epoch scope. The Y8 FORWARD_SHADOW PASS clear stays a `validate` rule.
- **(c) OPEN: clearing the INTEGRITY freeze.** W15 (ARCH:720-723) and AUT-6 r15:505 describe an incident clear "through the registry CLI on the C5 API", but no C5 transition kind can carry it, and HWM_RESET must not widen. Until AUT-6 files the row kind and its fold semantics, a venue INTEGRITY freeze is permanent (fail closed). AUT-6 owns this; it blocks no ARCH-0 seam.

## E-20 (coordinator, 2026-10-04; from the ARCH-0 seam A 7b build): malformed carried counters
- `FoldInvalidReason` gains `carried_counters_malformed`. An HWM_RESET row whose `carried_counters` does not parse to the exact shape makes the fold return this reason. Ignoring the carry instead would silently refund budget.
- The exact shape is:
  - top level: `{"lineages": {<root>: <13 tally fields>}, "venue": {...}}`;
  - exact keys;
  - `alpha_spent` as a canonical decimal string;
  - timestamp lists sorted.
- The store maps the reason to `engine_inconsistency`.

## E-21 (coordinator, 2026-10-04; from the ARCH-0 seam A 7b ARCH review): windowed tallies carry instants
- **Change.** Every windowed counter in ARCH C5, AUT-5 r7:108 and :484, and E-5 becomes a sorted tuple of effective instants (ns), not an int. This covers:
  - 30D rollbacks;
  - 7D infra resumes;
  - 30D drill counters;
  - 14D RECOVERABLE_MODEL resumes per lineage;
  - per-day drill-close restores;
  - the forward-window nomination slot;
  - Z3 sender changes, which also give the `ROLLBACK_MIN_DWELL_H` anchor.
- **Unchanged.** Lifetime quantities stay scalars: `nominations`, `infeasible_nominations`, `alpha_spent` and `terminal_frozen`.
- **Carried counters.** `carried_counters` (E-20 shape) uses the same keys and types. Lists merge by sorted multiset union, ints by max, bools by OR.
- **Windows.** Each window is evaluated by `validate` (7c/7d) as the length of the in-window slice.
- **Supersedes.** Plan r5:214-221 (int counters) is superseded.

## E-22 (coordinator, 2026-10-04; from the ARCH-0 seam A 8b ARCH review): what ROLLBACK and ROOT_ADMIT cite
- **(a) ROLLBACK** (ARCH:478, AUT-7 r5:192, :234). A ROLLBACK from the outgoing family F to the target G cites:
  - F's halting causes: FAIL verdicts whose subject is F and whose artefact is F's bound sha;
  - the AUT-6 DRIFT `fee_schedule` PASS for the champion.
  F's causes may be absent only when F's standing halt carries no verdict (an exec-store mirror, or a `rollback_failed` HALT).
- **(b) ROOT_ADMIT** (ARCH:479). A ROOT_ADMIT cites the DRIFT `fee_schedule` PASS, plus any root-admission verdicts that AUT-5 names.
- **(c) Lookup.** Replay and `validate` resolve each cited verdict in its subject family's verdict directory. The search is bounded to three places: the row's family, the batch partner, and the prior fold's senders. Every other verdict kind keeps the rule "PASS, subject = the row's family".
- **(d) Model class.** An artefact's model class is found by probing the closed set `pins.MODEL_CLASS_COMPONENTS` and requiring exactly one match. This replaces the assumption that every artefact lives under `<kind>:density_table` (AUT-3 r6:90 `rung_recalibration`).

## E-23 (coordinator, 2026-10-04; from the ARCH-0 seam A 8c ARCH and SEC reviews): resolve budget
- **Bound.** The resolve budget is a 2,000-row chain (about one year at 6 rows/day) in 5 s or less. This replaces "10k rows in 2 s". Measured: 1.35 s.
- **Growth.** Replay is quadratic: it re-folds `rows[:index]` for each batch (replay.py:493). The cost is roughly 1.35·(n/2000)² s, which reaches `ENGINE_LOCK_MAX_HOLD_S` at about 6.6k rows.
- **Backlog obligation.** Replay must fold incrementally, carrying the fold forward batch to batch, before the chain reaches 3,000 rows (about 16 months).
- **AUT-5a.** It logs resolve duration at every LAUNCH and relaunch.

## E-24 (coordinator, 2026-10-04; from the A8c-R4 adjudication): a family's manifest is immutable and its density pin is its artefact
- **Manifest sha.** A family's `manifest_sha256` is the one on its introducing row. A later row may carry only that same sha. This supersedes the "latest manifest sha" fold behaviour (fold.py:321-322).
- **Density pin.** The manifest's `density_artefact_sha256` equals the family's bound artefact sha, for every kind. Sentinel roots bind the sentinel file.
- **New density.** A new density is a new child family, minted. ARCH:367 was silent on manifest immutability; this erratum closes that gap.


<!-- E-25..E-28 filed 2026-10-06 from docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_r3.md (F1 FQ-PLAN; peer rounds 1-2 + convergence, rulings FQ-R34..R56). Consumed by their owning WPs; nothing here is built. -->
## E-25 (coordinator, 2026-10-04; FQ r3 RC-1 as amended by FQ-R15, FQ-R20, FQ-R26, FQ-R37, FQ-R38, FQ-R39, FQ-R55; filed by F1 only, FQ-R19): e-process verdicts and the per-lineage e-LOND α schedule

**Numbering.** The FQ plan's "E-15" is already used by the network-namespace erratum, so this one is E-25. Every FQ-plan reference to E-15, including F7b's Needs token, reads E-25.

**Finding.**
- ARCH C4 (`:288-301`, `:323-346`) and AUT-4 r11 (§3.1 `:469-472`, §3.5 `:560-572`) allow only a fixed-n, single-look FORWARD_SHADOW under a geometric FWER schedule.
- PREREG v2 confirms on an anytime-valid, calendar-day e-process and controls FDR with per-lineage e-LOND.
- Neither the `verdict/v1` key set (`src/breezy/persistence/autonomy/verdict.py:178-184`) nor the window-cap rule (ARCH `:340-346`) can express that.

**Rule.**

1. **New verdict fields.** These are three nullable additions to `verdict/v1` `_KEYS`, and all three are in the identity body.
   - **`test_kind`** ∈ {`fixed_n`, `e_process`}.
     - Never null on FORWARD_SHADOW.
     - On LIVE_SEQUENTIAL it is `e_process` only when the family PREREG registers an e-process. LD-OBF families keep it null; `family_prereg_sha256` governs them.
     - Null on every other kind.
   - **`eta_ns`** (int, `e_process` only). The projected UTC ns at which n reaches `n_e_power[k]`, at `take_rate_lower`. Null when the nomination is infeasible or the test is `fixed_n`.
   - **`window_end`** (ISO date, FORWARD_SHADOW only, either test kind). The last forward climate day, inclusive, by AUT-4 `windows.py` arithmetic.

2. **`n_min_eff` is not redefined.**
   - It is null on every `e_process` verdict.
   - For `e_process`, `n_min` is F5's pre-registered earliest-look n. No PASS or FAIL is written below it.

3. **The e-process (FORWARD_SHADOW and LIVE_SEQUENTIAL `e_process`).** The unit is the settled calendar day d.
   - **Null H0_a (per take).** E[h_i | G_τi] ≤ BE_i, where:
     - h_i ∈ {0, 1} is the qty-1 payout;
     - BE_i = haircut `ask_exec` + fee, with the existing minimum-ask floor on the ask kept unchanged (FQ-R55.2);
     - G_τi is the information at the decision instant.
   - **The per-take term, with the upside clipped (FQ-R55.2).**
     - X_i = min(h_i/BE_i − 1, `X_max`), where `X_max` is pinned in the F5 design JSON.
     - The downside is never clipped, so X_i ≥ −1 still holds.
     - Clipping only lowers X_i, so E[X_i | G_τi] ≤ 0 under H0_a still holds. Validity is kept and the upside tail is bounded.
   - **Voids and ties (FQ-R55.4).**
     - A voided take enters as X_i = 0 (and S_i = 0 below). It takes its slot and is never dropped.
     - Takes at one decision instant are ordered by G-measurable keys only: (station, rung id), lexicographic. No outcome-dependent or arrival-order key is used.
   - **The daily statistic uses a denominator pinned before the day (FQ-R39, FQ-R55.1).**
     - Y_d = (1/m_d) · Σ_{i ≤ min(N_d, m_d)} X_i, where N_d is the number of takes on day d.
     - **m_d = `m_cap`** for every day. `m_cap` is pinned in the F5 design JSON, **provisionally 2**. F5's joint power MC chooses between {2, 3}. m_d no longer depends on the listing count L_d.
     - Empty slots (N_d < m_d) contribute 0. A day with no takes has Y_d = 0, which gives a factor of 1.
     - Takes are counted in decision order (ties as above). Takes beyond m_d are excluded from Y_d and disclosed in the metric `eprocess_uncounted_takes`.
     - −1 ≤ Y_d ≤ `X_max`.
   - **e_a.** e_a,t = Π_{d ≤ t} (1 + λ_d·Y_d).
     - λ_d is fixed at the start of day d from settled days only (the betting rule is pinned).
     - λ_d ∈ [0, λ_max], with λ_max ≤ 0.5 (FQ-R15), so every factor is ≥ 0.5.
   - **e_b, a betting e-process built directly rather than derived from a CS (FQ-R39).**
     - S_i = (a_i − y_i)² − (p_i − y_i)², where a_i is the ask-implied probability of the side bought, p_i is the model's probability of that side, and y_i is the outcome.
     - The null is H0_b: E[S_i | G_τi] ≤ 0.
     - Z_d = (1/m_d)·Σ_{i ≤ min(N_d, m_d)} S_i ∈ [−1, 1], using the same m_d, the same tie order and the same void rule.
     - e_b,t = Π (1 + μ_d·Z_d), with μ_d predictable and in [0, μ_max ≤ 0.5].
     - The BSS-on-takes CS is still reported, as a diagnostic only.
   - **The two nulls are different (FQ-R55).**
     - H0_a (no net edge against the haircut ask) and H0_b (no Brier improvement against the ask) are distinct hypotheses. Neither implies the other.
     - PASS asserts **both** alternatives. It is an intersection–union test: it rejects H0_a ∪ H0_b only when each one is rejected at α_k.
   - **Outcomes.**
     - **PASS:** min(e_a, e_b) ≥ 1/α_k on some settled day with n ≥ `earliest_look_n`, **and** the calibration guard is sufficient and not failing.
       - Ville's inequality bounds P_H0a(sup e_a ≥ 1/α_k) ≤ α_k, and likewise for H0_b. So the IUT has level α_k.
     - **FAIL (KILL):** the hedged CS on Y_d (clipped X), at level 1 − **α_kill**, has UB < 0.
       - **KILL's null (FQ-R55).** It is E[Y_d | F_{d−}] ≥ 0 after the haircut and the clip: "the clipped, haircut daily mean is not negative". It is **not** "the model has no edge". A model with a small true edge that the haircut, the fee and the clip remove can be killed. That is accepted as capital protection.
       - **α_kill = 0.05**, pinned in the F5 design JSON. It is separate from α_k, is never charged to `alpha_spent`, and is not part of e-LOND. Rationale: KILL is a capital-protection decision, not a discovery claim.
       - **Compounding (FQ-R55).** Each re-nomination runs a new KILL test, so false-kill risk compounds across a lineage's tests. The lifetime cap bounds it. By the union bound, P(any false KILL across a lineage's FORWARD_SHADOW tests) ≤ K_LIFETIME·α_kill = 4·0.05 = 0.20. Infeasible nominations run no test, and `max_infeasible_nominations` caps them (rule 6). Each LIVE_SEQUENTIAL `e_process` tenure adds at most α_kill. F5 reports the realised bound.
     - **UNDERPOWERED:** otherwise.
     - **`INCONCLUSIVE(window_end_no_crossing)`:** the window ended without a crossing.
     - PASS, FAIL and INCONCLUSIVE are final and are never reopened.
     - On LIVE_SEQUENTIAL `e_process`, WIN is PASS and KILL is FAIL. The detector map is unchanged.
   - **Why a pinned denominator and not per-take factors (FQ-R39).**
     - The per-take product Π(1 + λ X_i) with a start-of-day λ is a test supermartingale only if each factor has conditional mean ≤ 1 given the earlier factors.
     - Takes on the same station-day settle together and are dependent. Mixed-side takes on one station-day are positively correlated (L-40 i).
     - The linear daily form is valid under any within-day dependence, and with a take count that depends on intraday information. Each term has conditional mean ≤ 0 at its own decision instant, the tower property applies, and the slot weights 1/m_cap are fixed before the day.
     - The cost is dilution on days with N_d < m_cap. F5's joint MC chooses `m_cap` ∈ {2, 3} to trade that dilution against P(N_d > m_cap).
   - **Mandatory MC cases (F5, L-40 and L-41).** Type-I error of PASS ≤ α_k is required in both exact-null cases:
     - (i) **Intraday-informed take count.** Takes fire when an intraday observation signal crosses a threshold, outcomes are correlated with that signal, and the true conditional edge is exactly 0.
     - (ii) **Mixed-side same-station-day takes** with positive covariance.
     - Both cases run at each candidate `m_cap` ∈ {2, 3}, with the pinned `X_max`.

4. **α schedule.** Each lineage root pins `alpha_schedule` ∈ {`halving_v1`, `elond_heavy_tailed_v1`} in the policy block.
   - **`halving_v1`** is ARCH's α_total·2^−k_life, unchanged.
   - **`elond_heavy_tailed_v1`** gives α_k = α_total·γ_k·(R + 1), where:
     - γ_t = g(t)/Σ_{s=1..T} g(s), with g(t) = 1/(t·ln²(t+1));
     - T = `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` (`pins.py:38`, which is 4), unless F5 pins per-epoch budgets. The design JSON pins exactly one of the two;
     - R = the lineage's effective CHALLENGER→CHAMPION PROMOTE count before the nomination row's `ts_ns`. That is the fold's `promotions` (`fold.py:397-398`; `fold_tallies.py:62`, `:87`). PROMOTE reaches CHAMPION only from CHALLENGER (`transitions.py:72`; FQ-R43 CONFIRMED).
   - **Why R is safe.** R ≤ the true discovery count, because each such PROMOTE needs an accepted FORWARD_SHADOW PASS (ARCH `:476`). If `promotions` is window-pruned (E-21), R only shrinks, which is conservative.
   - **Frozen at test start.** `alpha_k` is computed once, inside the nomination's `BEGIN IMMEDIATE`, and written to the row. FORWARD_SHADOW copies it.
   - **No pooling** across lineages. `alpha_spent` = Σ row `alpha_k`.
   - **Pairing rule.** The policy loader refuses `elond_heavy_tailed_v1` on a `fixed_n` lineage and `halving_v1` on an `e_process` lineage.

5. **Error-rate statement (FQ-R39).**
   - **What is controlled.** e-LOND controls FDR ≤ α_total **within each lineage's nomination sequence**, under arbitrary dependence among that lineage's e-values.
   - **The null.** A false discovery is a PASS when H0_k holds, where H0_k = H0_a ∪ H0_b for nominee k: no net edge against the **haircut ask** (on the clipped scale), or no Brier improvement against the **ask**.
   - **What PASS does not test.** PASS does **not** test superiority over the incumbent champion. That comparison is the non-confirmatory OFFLINE_CHALLENGER / NOT_DISTINCT screen.
   - **Across lineages, nothing is controlled.** With L lineages, this erratum does not bound the programme-wide false-discovery proportion.
   - **The FWER bound.** At R = 0, Σ_k α_k ≤ α_total. ARCH's "Σα ≤ α_total per lineage" (`:334`) holds for `halving_v1` lineages only. That is the FWER-to-FDR substitution this programme adopts.

6. **`nomination_feasible`.**
   - **`fixed_n`:** unchanged (`n_min_eff ≤ n_cap`).
   - **`e_process`:** true iff **both** of these hold:
     - (a) ⌊`take_rate_lower` · forward days to `window_end` · `uptime_floor`⌋ ≥ `n_e_power[k]`.
       - `n_e_power` is a pinned policy-block table of the smallest n with **joint** MC power ≥ 0.8 for the PASS rule min(e_a, e_b) ≥ 1/α_k, at R = 0, at the pinned `m_cap` and `X_max` (FQ-R55.3).
       - It is never derived from e_a power alone.
       - This is arithmetic on named block keys only (AUT-4 r11 K1);
     - (b) **(FQ-R38, GAP-13)** an F5 ruling registers a forward-only shadow evidence source for the nominee. While none exists, every `e_process` nomination of a non-champion is infeasible.
   - **An infeasible nomination burns no K slot:** `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` +1, and the window slot is used. ARCH `:343-344` is unchanged.
   - **Cap (FQ-R39).**
     - A nomination is refused, and no row is written, when the lineage's `infeasible_nominations` (`fold_tallies.py:59`, `:83`) is ≥ the policy key `max_infeasible_nominations`.
     - A new code ceiling owned by ARCH-0, `pins.MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME = 4`, bounds that key.
     - Rationale: infeasible nominations spend no α. Without a cap, a lineage can consume forward windows indefinitely, and can shop for a feasible window as `window_end` and the table index move. The cap only restricts.

7. **C5 row shape is unchanged.** All five `NOMINATION_FIELDS` stay required on a nomination (`registry_shape.py:41`, `:73-75`).
   - On an `e_process` row, `n_min_eff` holds the `fixed_n` value computed from the same block. It is disclosure only and never a gate.

8. **Evidence provenance (FQ-R37).**
   - No verdict PASS may rest on `source=backtest` rows. The evaluator enforces this: a statistic whose only input is backtest yields at most UNDERPOWERED, or a screen rejection.
   - The policy loader refuses a `forecast_quantile_ladder` lineage with `test_kind=fixed_n`.
   - Non-FQ fixed-n replay FS is unchanged and moot, because `pins.LIVE_GATE_ROUTED_KINDS` = {`forecast_quantile_ladder`} (`pins.py:23`).

9. **K_LIFETIME ≤ 4** stays a ceiling.

10. **Fixed-n-only rules.**
    - The single-look discipline (AUT-4 r11 §3.1) and the window-cap rule (ARCH `:340-346`) apply to `fixed_n` only.
    - `e_process` uses rules 3 and 6.

**Amends (the frozen text itself is not edited).**
- ARCH C4 `:288-301`, `:323-336` and `:340-346`.
- AUT-4 r11 §3.1, §3.1a, §3.5, §3.7, §3.8 and §7.
- The AUT-5 r7 policy key `alpha_spending` (`:599`).

**Consumption.**
- **ARCH-0 owner:**
  - three keys in `verdict.py:178-184`;
  - kind rules beside `_FORWARD_SHADOW_ONLY` (`:189`, `:264-270`);
  - the new pins ceiling (rule 6);
  - `persistence/autonomy/elond.py`.
- AUT-4 r12: F7b (WP2b).
- AUT-5 r8: policy keys and WP3 tests.
- **F5 design JSON pins:**
  - γ or T, δ_h, `n_e_power` (joint), `take_rate_lower`, `uptime_floor`, `earliest_look_n`;
  - `m_cap` (provisional 2; final ∈ {2, 3}), `X_max`, λ_max, μ_max, the betting rules, α_kill;
  - the parity n_par, δ_par and α_par, plus the parity bootstrap seed and replicate count (§R12-5), and `STALE_PARITY_H` (§R8-1).

**Tests (all ADD).**
- `test_c4_e_process_n_min_eff_null_with_eta_ns_window_end`
- `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26)
- `test_alpha_frozen_at_test_start_per_lineage_no_pooling`
- `test_infeasible_nomination_burns_no_k_slot`
- `test_infeasible_nominations_capped_per_lineage`
- `test_e_process_nomination_infeasible_without_forward_shadow_source`
- `test_elond_schedule_refused_for_fixed_n_lineage`
- `test_elond_r_counts_only_effective_champion_promotes`
- `test_verdict_e_process_fields_null_on_other_kinds`
- `test_eprocess_daily_denominator_fixed_before_first_decision`
- `test_eprocess_m_d_is_pinned_m_cap_independent_of_listing_count` (FQ-R55.1)
- `test_eprocess_uncounted_takes_disclosed_never_entered`
- `test_eprocess_upside_clipped_at_x_max_downside_never_clipped` (FQ-R55.2)
- `test_kill_cs_uses_clipped_haircut_y` (FQ-R55.2)
- `test_eprocess_same_instant_ties_ordered_by_station_then_rung_id` (FQ-R55.4)
- `test_eprocess_void_take_enters_as_zero_never_dropped` (FQ-R55.4)
- `test_eprocess_null_mc_intraday_dependent_take_count`
- `test_eprocess_null_mc_mixed_side_same_station_day`
- `test_n_e_power_is_joint_power_of_min_ea_eb` (FQ-R55.3; F5 design-JSON test)
- `test_e_b_is_betting_process_not_cs_derived`
- `test_alpha_kill_pinned_separately_never_charged`
- `test_backtest_only_input_never_yields_pass`
- `test_policy_loader_refuses_fq_lineage_fixed_n`

**Fail-closed reading.** Until a merged ARCH-0 change consumes E-25, the exact-set reader refuses any verdict carrying `test_kind`, and F7b cannot merge.

## E-26 (coordinator, 2026-10-04; FQ r3 RC-6 as amended by FQ-R20, FQ-R40; filed by F1 only): two FQ model classes

**Numbering.** The FQ plan's "E-16" is already used, so this one is E-26. The Needs of F11 and F13 read E-26.

**Finding.** Only `density_table` and `rung_recalibration` are admitted (ARCH C3 `:235-240`; AUT-3 r6 §3.1; `pins.MODEL_CLASS_COMPONENTS`, `pins.py:96`).

**Rule.**

1. **Two new classes.**
   - Add `forecast_quantile_ladder:density_table_multisource` and `forecast_quantile_ladder:variant_spec`.
   - `MODEL_CLASS_COMPONENTS` becomes `("density_table", "rung_recalibration", "density_table_multisource", "variant_spec")`. It is append-only.
   - `ROOT_ARTEFACT_COMPONENT` stays `"density_table"` (`pins.py:91`).
   - E-22(d) probing still requires exactly one match.
2. **Single writer.** Only AUT-3 `c3_writer.write_candidate` writes either class:
   - into a fresh `derived/artefacts/<model_class>/<sha>/`;
   - with `lineage/v1` and every C3 invariant (`ref_ts_lt_take_ts`, `no_sealed_holdout_rows_in_train`);
   - with one `refit_run/v1` per run.
3. **One mint slot.** ≤ 1 MINT per lineage per day across all four classes (ARCH `:323-325`).
4. **`density_table_multisource`.**
   - Inputs: US weather sources only. Never international data, venue prices or execution data (ARCH `:238-240`).
   - `data_windows` has one entry per source, each with its `content_sha256`.
   - It may be screened and forward-shadow-replayed. Becoming CHAMPION also needs the F13 ingest actor live, and a separately reviewed G11-style live-loader acceptance with parity tests.
5. **`variant_spec` (FQ-R40).**
   - **The variation lives in the artefact only.** A `variant_spec` child's manifest equals its committed root on every key outside the ARCH §4.2 allowlist (ARCH `:803-806`; `byte_binding.CHILD_MANIFEST_ALLOWLIST`, `byte_binding.py:82-91`).
   - `params` is a closed-key artefact object. Its keys come from the set the FQ live loader reads from an artefact, bounded by that loader (ARCH `:806`).
   - It never changes `taker_fee_coefficient`, `composition_kind` or `stations`.
6. **Nomination refusal (FQ-R40).**
   - A nomination of a child whose manifest differs from its root outside the §4.2 allowlist is **refused at nomination**.
   - Variation that needs a manifest change goes through new-family registration, never through a MINT.
7. **Forward freeze (FQ-R14).**
   - `variant_spec` `lineage.json` carries `spec_freeze_sha`.
   - `leakage_assertions` gains `nomination_days_after_spec_freeze`.
   - Scan and screen days never count as nomination evidence.

**Consumption.**
- `pins.py:96`, by the ARCH-0 owner.
- AUT-3 r7: `c3_writer` and the §3.1 table.
- F11 and F13.
- The AUT-4 OFFLINE_CHALLENGER screens all four classes.

**Tests (all ADD unless marked).**
- `test_model_class_components_append_only_four`. Any existing exact-set pin is widened by exactly these two entries in the same commit (SCOPE: widened by exactly two, never turned into a superset check).
- `test_c3_writer_only_writer_of_new_classes`. This must be a call-site AST check (FQ-R43).
- `test_mint_ceiling_shared_across_four_classes`
- `test_multisource_consumes_no_execution_data`
- `test_variant_spec_params_are_artefact_only`
- `test_variant_spec_refuses_theta_kind_or_new_station`
- `test_variant_spec_nonallowlisted_diff_nomination_refused` (FQ-R40)
- `test_variant_spec_nomination_days_after_spec_freeze`

**Fail-closed reading.** Until E-26 is consumed, `c3_writer` refuses both classes, and the replay probe finds no component, so it refuses.

**Carried to F10.** M1 cells are (side, ask bin). The FQ manifest has no such key (`pm_us_crh_fq_v1.json:1-20`), and a child cannot vary it. An M1 survivor therefore needs either a reviewed FQ manifest-schema extension (outside E-26) or a new family (FQ-R40).

## E-27 (coordinator, 2026-10-04; FQ-R35 as amended by FQ-R46, FQ-R47, FQ-R48, FQ-R52): BOOTSTRAP_SEED CHAMPION is the venue's sending FQ root

**Amends RC-5 (FQ-R52).** This erratum amends FQ r3 RC-5's "F9 arms v2 through registry ROOT_ADMIT/RESUME" (`FQ-LOSS-RESPONSE_plan_r3.md:74`). It now reads:
- v2 is armed by the env and the RC-5 live-orders ruling (F9-A, F9-B).
- v2 enters the registry as the `BOOTSTRAP_SEED` CHAMPION.
- Neither ROOT_ADMIT nor RESUME is on the F9 path.

**Rule.**

1. **The CHAMPION seed.** In ARCH `:472` and `:737-738`, the `pins.BOOTSTRAP_SEED` CHAMPION reads "the venue's sending FQ root at bootstrap".
   - For polymarket_us this is `pm_us_crh_fq_v2`.
   - `pm_us_crh_fq_v1` is seeded **RETIRED**, beside v4, cont and `pm_us_crh_v2`.
   - The pair BOOTSTRAP (∅, RETIRED) is allowed (`transitions.py:69`).
   - **Evidence that this is safe now:** no bootstrap has run, and `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` is empty (`pins.py:99-100`; asserted by `test_empty_pins_at_arch0`, `test_autonomy_pins.py:104`).

2. **Other mentions of `fq_v1` (CONFLICT-7; FQ-R52).**
   - **Readings.** Where ARCH C3, C5, §5.3 or §10 names `fq_v1` as drill root, incumbent or rollback target (`:264`, `:480`, `:607`, `:1255`, `:1258`), it reads "the venue's FQ CHAMPION at drill time".
   - **The drill child.** `pm_us_crh_fq_v1_r0001` (`:1256`) reads `<champion>_r0001`. With v2 seeded, that is `pm_us_crh_fq_v2_r0001`.
   - **Historical, with no new reading.** These lines record the state at Rev 9.2 and are not re-read:
     - `:35` (G1, "currently `pm_us_crh_fq_v1`");
     - `:68-69` (G34, G35);
     - AUT-7 r5 `:29`, the ARCH §10 quote.

3. **Ordering (FQ-R48).**
   - The sequence is binding: **F9-A → F9-B (verified) → {P-1, P-2, GAP-16 pins} → bootstrap → P-3.**
   - P-1 also lands after F3 (FQ-R33).
   - The seed CHAMPION must hold its own `_LIVE_ORDERS_ALLOWLIST` triple at the P-1 commit.
   - E-24 holds: v2 has no registry row before F9-A.
   - Stage S follows F9-B. No session before F9-B ever counts toward L1.

4. **Seeded-retired lineages (FQ-R46; replaces r2 rule 4, which is deleted).**
   - **(a) The W15 clear precondition.** FQ-R34's precondition for clearing v1's standing halt reads: "the fold shows v1 RETIRED **and no family of v1's lineage is in any other state**".
     - The fold flag `terminal_frozen` is not part of the precondition.
     - The fold is unchanged. A BOOTSTRAP → RETIRED row sets no freeze, so every existing `terminal_frozen` assertion stays byte-unchanged.
   - **(b) The validate rule, owned by ARCH-0 and restrictive only: "a MINT is refused when every family of its lineage is RETIRED".** (FQ-R56; narrowed from r3's "lineage root is RETIRED". The broader rule conflicted with ARCH `:489`, under which a superseded root routinely ends RETIRED in a healthy lineage.)
     - It is added to `_CHECKS[Kind.MINT]` (`validate.py:526`) beside `ii.mint_rate` (`validate_ii.py:248-264`), as a new `validate_ii` check with a new `RuleII` member, refusing with `FAIL`.
     - The lineage's family states are read from `ctx.states`, which starts as the prior fold and is advanced by the earlier immediate rows in the batch (`validate.py:604`, `:623-624`). So a MINT that follows, in the same batch, a row that retires the lineage's last non-RETIRED family is also refused.
     - The check runs after `ii.mint_rate`, so the RED tests use the day's first MINT.
     - **SCOPE (FQ-R56):** `RULE_II_NAMES` (`tests/unit/test_registry_validate_ii.py:1254`, used by `test_every_rule_ii_name_is_unique_and_wired`) is widened by exactly the one new name, in the same commit.
     - **Why this is needed.** Y10 `terminal_frozen` (`validate_ii.py:208-219`) guards only →CHAMPION rows. MINT's checks today are `ii.mint_rate` alone (`validate.py:526`). So nothing currently stops a MINT in an all-RETIRED lineage. With this rule, (a) stays true once it holds.

**Unchanged.**
- ROOT_ADMIT (ARCH `:479`) stays the recovery path after a KILL or a TERMINAL event, including its U2 standing-halt rule.
- `ROOT_ADMIT_ENABLED_CEILING` stays `False` (`pins.py:22`).

**Consumption.**
- **ARCH-0 owner, as pins and validate commits:**
  - The `BOOTSTRAP_SEED` re-pin (P-1).
  - The `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` rows (P-1).
  - **The GAP-16 pins entry (FQ-R47):** `pins.DEFAULT_RESTRICTIVE_CLASS` (`pins.py:148-164`; ARCH `:372` names this literal) gains `"parity.fq_v2_shadow_live": ("DEMOTE", "RECOVERABLE_MODEL")`. It lands at or before P-1.
  - The rule 4(b) MINT check in `validate.py` and `validate_ii.py`.
- AUT-5 r8: §R8-3 line 172; §R8-4.
- AUT-7 r6: the retargets (§R8-3).

**Tests.**
- **SCOPE (re-pin)** `tests/unit/test_autonomy_pins.py::test_literal_identity_pins` (`:113-122`). The exact-equality assertion on `pins.BOOTSTRAP_SEED` is kept. The expected literal becomes the E-27 seed (`pm_us_crh_fq_v2` CHAMPION; v1, v4, cont and `pm_us_crh_v2` RETIRED) in the P-1 commit.
- **SCOPE (re-pin)** `test_autonomy_pins.py::test_empty_pins_at_arch0` (`:97-105`). The `BOOTSTRAPPED_ROOT_MANIFEST_SHA256 == {}` assertion (`:104`) keeps exact equality, re-pinned to the exact five-row P-1 literal. The `MappingProxyType` check (`:105`) is byte-unchanged. `test_bootstrapped_root_manifests_unchanged` (`:359-361`) is byte-unchanged and then hashes those five files.
- **ADD (assertion)** to `test_default_restrictive_class_is_demote_or_halt_with_known_classes` (`test_autonomy_pins.py:148-158`): `assert table["parity.fq_v2_shadow_live"] == ("DEMOTE", "RECOVERABLE_MODEL")`. The existing assertions are byte-unchanged. The test pins no exact key set, so no widening is needed.
- ADD `test_bootstrap_seed_champion_has_live_orders_triple`
- ADD `test_policy_halt_mirror_on_seeded_retired_family_writes_no_row_and_no_freeze`
- ADD `test_mint_in_all_retired_lineage_refused` (FQ-R46, FQ-R56)
- ADD `test_mint_after_lineage_fully_retired_earlier_in_same_batch_refused` (FQ-R46, FQ-R56, the batch-aware read)
- ADD `test_mint_allowed_when_root_retired_but_lineage_has_live_family` (FQ-R56: a superseded root that is RETIRED does not block MINT in a healthy lineage)
- **Verify-first (FQ-R46, blocking).** List every existing test that writes a MINT in a lineage whose families are all, or all become, RETIRED. If any exists, STOP for a ruling. Its assertion is never edited to pass.
- **Dropped:** r2's `test_seeded_retired_lineage_is_terminal_frozen`. It was an r2 proposal that never merged, and its rule is rejected.

## E-28 (coordinator, 2026-10-04; FQ-R36 as reworded by FQ-R50): RC-7 carve-out from AUT-5a's `app/trade.py` ownership

**Rule.**
- The ARCH §5.1 sentence "`app/trade.py` … belong[s] to AUT-5a alone" (`:1049-1051`) reads: "except that FQ r3 row F6 may change `_compose_forecast_quantile_ladder` (`app/trade.py:676`) once. **F6 merges before any row-7 WP that edits `app/trade.py` (WP5).**"
- **"Row 7 merged" means that row 7's last WP has merged.**
- Row-7 WPs that do not edit `app/trade.py` may merge before F6 (FQ-R48). Work after row 7 merges, such as F13, is outside AUT-5a's in-flight exclusivity and is unaffected.
